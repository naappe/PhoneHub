using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;

namespace AndroidBridge
{
    internal static class AdbProxyV2
    {
        private const string ServerRemote = "/data/local/tmp/scrcpy-server.jar";

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

        private static int RunPassthrough(string exe, IEnumerable<string> args)
        {
            var psi = new ProcessStartInfo
            {
                FileName = exe,
                Arguments = String.Join(" ", args.Select(QuoteArg)),
                UseShellExecute = false,
                CreateNoWindow = true
            };

            using (var process = Process.Start(psi))
            {
                process.WaitForExit();
                return process.ExitCode;
            }
        }

        private static string RunCapture(string exe, IEnumerable<string> args)
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

            using (var process = Process.Start(psi))
            {
                string stdout = process.StandardOutput.ReadToEnd();
                process.StandardError.ReadToEnd();
                process.WaitForExit();
                return process.ExitCode == 0 ? stdout : "";
            }
        }

        private static string Sha256File(string path)
        {
            using (var sha = SHA256.Create())
            using (var stream = File.OpenRead(path))
            {
                return BitConverter.ToString(sha.ComputeHash(stream))
                    .Replace("-", "")
                    .ToLowerInvariant();
            }
        }

        private static string RemoteSha256(
            string realAdb,
            string serial)
        {
            var args = new List<string>();

            if (!String.IsNullOrWhiteSpace(serial))
            {
                args.Add("-s");
                args.Add(serial);
            }

            args.Add("shell");
            args.Add("sha256sum");
            args.Add(ServerRemote);

            string output = RunCapture(realAdb, args);
            string token = (output ?? "")
                .Split(new[] { ' ', '\t', '\r', '\n' },
                    StringSplitOptions.RemoveEmptyEntries)
                .FirstOrDefault() ?? "";

            return token.Length == 64 && token.All(Uri.IsHexDigit)
                ? token.ToLowerInvariant()
                : "";
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

                if (String.Equals(args[i], "push",
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
                    "AndroidBridge: real adb.exe is unavailable.");
                return 1;
            }

            string serial;
            string localFile;

            if (IsScrcpyServerPush(args, out serial, out localFile))
            {
                if (!File.Exists(localFile))
                {
                    Console.Error.WriteLine(
                        "AndroidBridge: local scrcpy server is missing.");
                    return 1;
                }

                string localHash = Sha256File(localFile);
                string remoteHash = RemoteSha256(realAdb, serial);

                if (remoteHash == localHash)
                {
                    Console.WriteLine(
                        "AndroidBridge: verified server already staged; push skipped.");
                    return 0;
                }

                Console.Error.WriteLine(
                    "AndroidBridge: staged server does not match; refusing slow sync push.");
                return 1;
            }

            return RunPassthrough(realAdb, args);
        }
    }
}
