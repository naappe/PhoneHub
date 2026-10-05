using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading;

namespace AndroidBridge
{
    internal static class AdbProxy
    {
        private const int ChunkSize = 65536;
        private const string ServerRemote = "/data/local/tmp/scrcpy-server.jar";
        private const string StageRemote = "/data/local/tmp/androidbridge-scrcpy-server.tmp";
        private const string ChunkRemote = "/data/local/tmp/androidbridge-scrcpy-chunk.tmp";

        private sealed class Result
        {
            public int Code;
            public string Stdout = "";
            public string Stderr = "";
        }

        private static string Quote(string value)
        {
            if (value == null) return """";
            return """ + value.Replace("\", "\\").Replace(""", "\"") + """;
        }

        private static Result Run(string exe, IEnumerable<string> args, int timeoutMs = 120000)
        {
            var psi = new ProcessStartInfo
            {
                FileName = exe,
                Arguments = string.Join(" ", args.Select(Quote)),
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };

            using (var p = new Process { StartInfo = psi })
            {
                p.Start();

                string stdout = p.StandardOutput.ReadToEnd();
                string stderr = p.StandardError.ReadToEnd();

                if (!p.WaitForExit(timeoutMs))
                {
                    try { p.Kill(); } catch { }
                    return new Result { Code = 124, Stdout = stdout, Stderr = stderr + "\nTimeout" };
                }

                return new Result { Code = p.ExitCode, Stdout = stdout, Stderr = stderr };
            }
        }

        private static List<string> PrefixForSerial(string serial)
        {
            var a = new List<string>();
            if (!string.IsNullOrWhiteSpace(serial))
            {
                a.Add("-s");
                a.Add(serial);
            }
            return a;
        }

        private static Result Adb(string realAdb, string serial, params string[] tail)
        {
            var args = PrefixForSerial(serial);
            args.AddRange(tail);
            return Run(realAdb, args);
        }

        private static string Sha256File(string path)
        {
            using (var sha = SHA256.Create())
            using (var fs = File.OpenRead(path))
            {
                var hash = sha.ComputeHash(fs);
                return BitConverter.ToString(hash).Replace("-", "").ToLowerInvariant();
            }
        }

        private static string RemoteSha256(string realAdb, string serial, string path)
        {
            var r = Adb(realAdb, serial, "shell", "sha256sum", path);
            if (r.Code != 0) return "";

            string text = (r.Stdout ?? "").Trim();
            if (text.Length < 64) return "";

            string token = text.Split(new[] { ' ', '\t', '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
                               .FirstOrDefault() ?? "";

            if (token.Length == 64 && token.All(Uri.IsHexDigit))
                return token.ToLowerInvariant();

            return "";
        }

        private static long RemoteSize(string realAdb, string serial, string path)
        {
            var r = Adb(realAdb, serial, "shell", "wc", "-c", path);
            if (r.Code != 0) return -1;

            string token = (r.Stdout ?? "")
                .Split(new[] { ' ', '\t', '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
                .FirstOrDefault();

            long n;
            return long.TryParse(token, NumberStyles.Integer, CultureInfo.InvariantCulture, out n) ? n : -1;
        }

        private static bool RemoteServerMatches(string realAdb, string serial, string localFile)
        {
            long localSize = new FileInfo(localFile).Length;
            long remoteSize = RemoteSize(realAdb, serial, ServerRemote);

            if (remoteSize != localSize)
                return false;

            string localHash = Sha256File(localFile);
            string remoteHash = RemoteSha256(realAdb, serial, ServerRemote);

            // Hash verification is preferred. Size is a compatibility fallback
            // for Android builds without sha256sum.
            return string.IsNullOrEmpty(remoteHash) || remoteHash == localHash;
        }

        private static bool PushChunkWithRetry(
            string realAdb,
            string serial,
            string localChunk,
            int maxAttempts = 5)
        {
            for (int attempt = 1; attempt <= maxAttempts; attempt++)
            {
                var push = Adb(realAdb, serial, "push", localChunk, ChunkRemote);

                if (push.Code == 0)
                    return true;

                Thread.Sleep(500 * attempt);
            }

            return false;
        }

        private static int InstallServerChunked(string realAdb, string serial, string localFile)
        {
            if (!File.Exists(localFile))
            {
                Console.Error.WriteLine("AndroidBridge ADB proxy: local scrcpy server not found.");
                return 1;
            }

            if (RemoteServerMatches(realAdb, serial, localFile))
            {
                Console.WriteLine("AndroidBridge: scrcpy server already verified on phone; upload skipped.");
                return 0;
            }

            Adb(realAdb, serial, "shell", "rm", "-f", StageRemote, ChunkRemote);

            string tempChunk = Path.Combine(
                Path.GetTempPath(),
                "androidbridge-scrcpy-" + Process.GetCurrentProcess().Id + ".chunk");

            try
            {
                byte[] buffer = new byte[ChunkSize];
                bool first = true;

                using (var input = File.OpenRead(localFile))
                {
                    while (true)
                    {
                        int count = input.Read(buffer, 0, buffer.Length);
                        if (count <= 0)
                            break;

                        using (var outFile = new FileStream(tempChunk, FileMode.Create, FileAccess.Write, FileShare.None))
                        {
                            outFile.Write(buffer, 0, count);
                        }

                        if (!PushChunkWithRetry(realAdb, serial, tempChunk))
                        {
                            Console.Error.WriteLine("AndroidBridge ADB proxy: a 64 KB server chunk could not be transferred.");
                            return 1;
                        }

                        string redir = first ? ">" : ">>";
                        var append = Adb(
                            realAdb,
                            serial,
                            "shell",
                            "sh",
                            "-c",
                            "cat " + ChunkRemote + " " + redir + " " + StageRemote);

                        if (append.Code != 0)
                        {
                            Console.Error.WriteLine(append.Stderr);
                            return append.Code == 0 ? 1 : append.Code;
                        }

                        first = false;
                    }
                }

                long localSize = new FileInfo(localFile).Length;
                long remoteSize = RemoteSize(realAdb, serial, StageRemote);

                if (remoteSize != localSize)
                {
                    Console.Error.WriteLine(
                        "AndroidBridge ADB proxy: staged server size mismatch (" +
                        remoteSize + " != " + localSize + ").");
                    return 1;
                }

                string localHash = Sha256File(localFile);
                string remoteHash = RemoteSha256(realAdb, serial, StageRemote);

                if (!string.IsNullOrEmpty(remoteHash) && remoteHash != localHash)
                {
                    Console.Error.WriteLine("AndroidBridge ADB proxy: staged server checksum mismatch.");
                    return 1;
                }

                var move = Adb(realAdb, serial, "shell", "mv", StageRemote, ServerRemote);
                if (move.Code != 0)
                {
                    Console.Error.WriteLine(move.Stderr);
                    return move.Code == 0 ? 1 : move.Code;
                }

                Adb(realAdb, serial, "shell", "rm", "-f", ChunkRemote);

                Console.WriteLine(
                    "AndroidBridge: scrcpy server installed in verified 64 KB chunks (" +
                    localSize + " bytes).");

                return 0;
            }
            finally
            {
                try { if (File.Exists(tempChunk)) File.Delete(tempChunk); } catch { }
            }
        }

        private static bool IsScrcpyServerPush(string[] args, out string serial, out string localFile)
        {
            serial = "";
            localFile = "";

            for (int i = 0; i < args.Length - 1; i++)
            {
                if (args[i] == "-s" && i + 1 < args.Length)
                    serial = args[i + 1];

                if (string.Equals(args[i], "push", StringComparison.OrdinalIgnoreCase) &&
                    i + 2 < args.Length)
                {
                    string remote = args[i + 2].Replace('\\', '/');

                    if (string.Equals(remote, ServerRemote, StringComparison.Ordinal))
                    {
                        localFile = args[i + 1];
                        return true;
                    }
                }
            }

            return false;
        }

        public static int Main(string[] args)
        {
            string realAdb = Environment.GetEnvironmentVariable("ANDROIDBRIDGE_REAL_ADB") ?? "";

            if (string.IsNullOrWhiteSpace(realAdb) || !File.Exists(realAdb))
            {
                Console.Error.WriteLine("AndroidBridge ADB proxy: real adb.exe path is unavailable.");
                return 1;
            }

            string serial;
            string localFile;

            if (IsScrcpyServerPush(args, out serial, out localFile))
                return InstallServerChunked(realAdb, serial, localFile);

            var result = Run(realAdb, args, 180000);

            if (!string.IsNullOrEmpty(result.Stdout))
                Console.Out.Write(result.Stdout);

            if (!string.IsNullOrEmpty(result.Stderr))
                Console.Error.Write(result.Stderr);

            return result.Code;
        }
    }
}
