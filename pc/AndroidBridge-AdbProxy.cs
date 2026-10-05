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

        private static string QuoteArg(string value)
        {
            if (String.IsNullOrEmpty(value))
                return "\"\"";

            if (!value.Any(c => Char.IsWhiteSpace(c) || c == '"'))
                return value;

            var sb = new StringBuilder();
            sb.Append('"');
            int backslashes = 0;

            foreach (char c in value)
            {
                if (c == '\\')
                {
                    backslashes++;
                    continue;
                }

                if (c == '"')
                {
                    sb.Append('\\', backslashes * 2 + 1);
                    sb.Append('"');
                    backslashes = 0;
                    continue;
                }

                if (backslashes > 0)
                {
                    sb.Append('\\', backslashes);
                    backslashes = 0;
                }

                sb.Append(c);
            }

            if (backslashes > 0)
                sb.Append('\\', backslashes * 2);

            sb.Append('"');
            return sb.ToString();
        }

        private static Result Run(
            string exe,
            IEnumerable<string> args,
            int timeoutMs)
        {
            var psi = new ProcessStartInfo
            {
                FileName = exe,
                Arguments = String.Join(" ", args.Select(QuoteArg)),
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true
            };

            using (var process = new Process())
            {
                process.StartInfo = psi;
                process.Start();

                string stdout = "";
                string stderr = "";

                var stdoutThread = new Thread(() =>
                {
                    try { stdout = process.StandardOutput.ReadToEnd(); }
                    catch { }
                });

                var stderrThread = new Thread(() =>
                {
                    try { stderr = process.StandardError.ReadToEnd(); }
                    catch { }
                });

                stdoutThread.Start();
                stderrThread.Start();

                bool exited;

                if (timeoutMs <= 0)
                {
                    process.WaitForExit();
                    exited = true;
                }
                else
                {
                    exited = process.WaitForExit(timeoutMs);
                }

                if (!exited)
                {
                    try { process.Kill(); } catch { }
                }

                try { stdoutThread.Join(2000); } catch { }
                try { stderrThread.Join(2000); } catch { }

                return new Result
                {
                    Code = exited ? process.ExitCode : 124,
                    Stdout = stdout,
                    Stderr = stderr + (exited ? "" : Environment.NewLine + "Timeout")
                };
            }
        }

        private static int RunPassthrough(
            string exe,
            IEnumerable<string> args)
        {
            var psi = new ProcessStartInfo
            {
                FileName = exe,
                Arguments = String.Join(" ", args.Select(QuoteArg)),
                UseShellExecute = false,
                CreateNoWindow = true
            };

            using (var process = new Process())
            {
                process.StartInfo = psi;
                process.Start();
                process.WaitForExit();
                return process.ExitCode;
            }
        }

        private static Result RunAdb(
            string realAdb,
            string serial,
            int timeoutMs,
            params string[] tail)
        {
            var args = new List<string>();

            if (!String.IsNullOrWhiteSpace(serial))
            {
                args.Add("-s");
                args.Add(serial);
            }

            args.AddRange(tail);
            return Run(realAdb, args, timeoutMs);
        }

        private static Result RunAdbRetry(
            string realAdb,
            string serial,
            int attempts,
            params string[] tail)
        {
            Result last = null;

            for (int attempt = 1; attempt <= attempts; attempt++)
            {
                last = RunAdb(realAdb, serial, 30000, tail);

                if (last.Code == 0)
                    return last;

                Thread.Sleep(300 * attempt);
            }

            return last ?? new Result
            {
                Code = 1,
                Stderr = "ADB command failed."
            };
        }

        private static string Sha256File(string path)
        {
            using (var sha = SHA256.Create())
            using (var stream = File.OpenRead(path))
            {
                byte[] hash = sha.ComputeHash(stream);

                return BitConverter
                    .ToString(hash)
                    .Replace("-", "")
                    .ToLowerInvariant();
            }
        }

        private static long RemoteSize(
            string realAdb,
            string serial,
            string remotePath)
        {
            var result = RunAdbRetry(
                realAdb,
                serial,
                3,
                "shell",
                "wc",
                "-c",
                remotePath);

            if (result.Code != 0)
                return -1;

            string token = (result.Stdout ?? "")
                .Split(
                    new[] { ' ', '\t', '\r', '\n' },
                    StringSplitOptions.RemoveEmptyEntries)
                .FirstOrDefault();

            long size;

            return Int64.TryParse(
                token,
                NumberStyles.Integer,
                CultureInfo.InvariantCulture,
                out size)
                ? size
                : -1;
        }

        private static string RemoteSha256(
            string realAdb,
            string serial,
            string remotePath)
        {
            var result = RunAdbRetry(
                realAdb,
                serial,
                2,
                "shell",
                "sha256sum",
                remotePath);

            if (result.Code != 0)
                return "";

            string token = (result.Stdout ?? "")
                .Split(
                    new[] { ' ', '\t', '\r', '\n' },
                    StringSplitOptions.RemoveEmptyEntries)
                .FirstOrDefault() ?? "";

            return token.Length == 64 && token.All(Uri.IsHexDigit)
                ? token.ToLowerInvariant()
                : "";
        }

        private static bool RemoteServerMatches(
            string realAdb,
            string serial,
            string localFile)
        {
            long localSize = new FileInfo(localFile).Length;
            long remoteSize = RemoteSize(realAdb, serial, ServerRemote);

            if (remoteSize != localSize)
                return false;

            string remoteHash = RemoteSha256(realAdb, serial, ServerRemote);

            if (String.IsNullOrEmpty(remoteHash))
                return true;

            return remoteHash == Sha256File(localFile);
        }

        private static bool PushChunk(
            string realAdb,
            string serial,
            string localChunk)
        {
            for (int attempt = 1; attempt <= 5; attempt++)
            {
                var result = RunAdb(
                    realAdb,
                    serial,
                    30000,
                    "push",
                    localChunk,
                    ChunkRemote);

                if (result.Code == 0)
                    return true;

                Thread.Sleep(400 * attempt);
            }

            return false;
        }

        private static bool AppendChunk(
            string realAdb,
            string serial,
            bool first)
        {
            string redirect = first ? ">" : ">>";
            string command =
                "cat " + ChunkRemote + " " +
                redirect + " " + StageRemote;

            var result = RunAdbRetry(
                realAdb,
                serial,
                4,
                "shell",
                "sh",
                "-c",
                command);

            return result.Code == 0;
        }

        private static int InstallServerChunked(
            string realAdb,
            string serial,
            string localFile)
        {
            if (!File.Exists(localFile))
            {
                Console.Error.WriteLine(
                    "AndroidBridge: local scrcpy-server file was not found.");
                return 1;
            }

            if (RemoteServerMatches(realAdb, serial, localFile))
            {
                Console.WriteLine(
                    "AndroidBridge: verified scrcpy server already on phone; upload skipped.");
                return 0;
            }

            RunAdbRetry(
                realAdb,
                serial,
                3,
                "shell",
                "rm",
                "-f",
                StageRemote,
                ChunkRemote);

            string tempChunk = Path.Combine(
                Path.GetTempPath(),
                "androidbridge-scrcpy-" +
                Process.GetCurrentProcess().Id +
                ".chunk");

            try
            {
                byte[] buffer = new byte[ChunkSize];
                bool first = true;
                int chunkNumber = 0;

                using (var input = File.OpenRead(localFile))
                {
                    while (true)
                    {
                        int count = input.Read(buffer, 0, buffer.Length);

                        if (count <= 0)
                            break;

                        chunkNumber++;

                        using (var output = new FileStream(
                            tempChunk,
                            FileMode.Create,
                            FileAccess.Write,
                            FileShare.None))
                        {
                            output.Write(buffer, 0, count);
                        }

                        if (!PushChunk(realAdb, serial, tempChunk))
                        {
                            Console.Error.WriteLine(
                                "AndroidBridge: scrcpy server chunk " +
                                chunkNumber +
                                " could not be transferred.");
                            return 1;
                        }

                        if (!AppendChunk(realAdb, serial, first))
                        {
                            Console.Error.WriteLine(
                                "AndroidBridge: could not assemble scrcpy server chunk " +
                                chunkNumber + ".");
                            return 1;
                        }

                        first = false;
                    }
                }

                long expectedSize = new FileInfo(localFile).Length;
                long stagedSize = RemoteSize(
                    realAdb,
                    serial,
                    StageRemote);

                if (stagedSize != expectedSize)
                {
                    Console.Error.WriteLine(
                        "AndroidBridge: staged scrcpy server size mismatch: " +
                        stagedSize + " != " + expectedSize + ".");
                    return 1;
                }

                string remoteHash = RemoteSha256(
                    realAdb,
                    serial,
                    StageRemote);

                if (!String.IsNullOrEmpty(remoteHash) &&
                    remoteHash != Sha256File(localFile))
                {
                    Console.Error.WriteLine(
                        "AndroidBridge: staged scrcpy server checksum mismatch.");
                    return 1;
                }

                var move = RunAdbRetry(
                    realAdb,
                    serial,
                    3,
                    "shell",
                    "mv",
                    StageRemote,
                    ServerRemote);

                if (move.Code != 0)
                {
                    Console.Error.WriteLine(
                        "AndroidBridge: could not activate the staged scrcpy server.");
                    return 1;
                }

                RunAdbRetry(
                    realAdb,
                    serial,
                    2,
                    "shell",
                    "rm",
                    "-f",
                    ChunkRemote);

                Console.WriteLine(
                    "AndroidBridge: scrcpy server installed in verified 64 KB chunks (" +
                    expectedSize + " bytes).");

                return 0;
            }
            finally
            {
                try
                {
                    if (File.Exists(tempChunk))
                        File.Delete(tempChunk);
                }
                catch { }
            }
        }

        private static bool IsScrcpyServerPush(
            string[] args,
            out string serial,
            out string localFile)
        {
            serial = "";
            localFile = "";

            for (int i = 0; i < args.Length; i++)
            {
                if (args[i] == "-s" && i + 1 < args.Length)
                    serial = args[i + 1];

                if (String.Equals(
                    args[i],
                    "push",
                    StringComparison.OrdinalIgnoreCase) &&
                    i + 2 < args.Length)
                {
                    string remote = args[i + 2].Replace('\\', '/');

                    if (remote == ServerRemote)
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
            string realAdb =
                Environment.GetEnvironmentVariable(
                    "ANDROIDBRIDGE_REAL_ADB") ?? "";

            if (String.IsNullOrWhiteSpace(realAdb) ||
                !File.Exists(realAdb))
            {
                Console.Error.WriteLine(
                    "AndroidBridge ADB proxy: real adb.exe path is unavailable.");
                return 1;
            }

            string serial;
            string localFile;

            if (IsScrcpyServerPush(
                args,
                out serial,
                out localFile))
            {
                return InstallServerChunked(
                    realAdb,
                    serial,
                    localFile);
            }

            // All non-push ADB commands pass through unchanged and inherit
            // this proxy's stdout/stderr handles. This is important because
            // scrcpy watches live server output while the adb shell process
            // remains active.
            return RunPassthrough(realAdb, args);
        }
    }
}
