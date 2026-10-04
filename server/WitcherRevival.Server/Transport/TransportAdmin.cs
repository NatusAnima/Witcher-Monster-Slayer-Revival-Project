using System.Text.Json;

namespace WitcherRevival.Server.Transport;

/// <summary>Local operator command. Tokens and player contents are never accepted or printed.</summary>
public static class TransportAdmin
{
    public static int Run(string[] args)
    {
        try
        {
            if (args.Length < 2) throw new ArgumentException();
            string action = args[1];
            var options = new Dictionary<string, string>(); bool newProfile = false;
            for (int i = 2; i < args.Length; i++)
            {
                if (args[i] == "--new-profile" && !newProfile) { newProfile = true; continue; }
                if (i + 1 == args.Length || args[i] is not ("--registry" or "--profiles" or "--code" or "--profile" or "--ttl-seconds" or "--slots"))
                    throw new ArgumentException();
                if (!options.TryAdd(args[i], args[++i])) throw new ArgumentException();
            }
            var store = new TransportRegistry(options["--registry"]);
            object result;
            if (action == "list" && options.Keys.All(k => k is "--registry" or "--profiles") && !newProfile)
                result = new { status = "ok", entries = store.List() };
            else if (action == "revoke" && options.Keys.All(k => k is "--registry" or "--profiles" or "--code") && !newProfile)
            { var e = store.Revoke(options["--code"]); result = new { status = "revoked", code = e.Code }; }
            else if (action == "approve" && !options.ContainsKey("--slots"))
            {
                var e = store.Approve(options["--code"], options["--profiles"], options.GetValueOrDefault("--profile"),
                    newProfile, int.Parse(options.GetValueOrDefault("--ttl-seconds", "2592000")));
                result = new { status = "approved", code = e.Code, profile = e.Profile, expiresAt = e.ExpiresAt };
            }
            else if (action == "renew" && !newProfile &&
                options.Keys.All(k => k is "--registry" or "--profiles" or "--code" or "--ttl-seconds"))
            {
                var e = store.Renew(options["--code"], int.Parse(options.GetValueOrDefault("--ttl-seconds", "2592000")));
                result = new { status = "approved", code = e.Code, profile = e.Profile, expiresAt = e.ExpiresAt };
            }
            else if (action == "open" && !newProfile &&
                options.Keys.All(k => k is "--registry" or "--profiles" or "--ttl-seconds" or "--slots"))
                result = store.OpenEnrollment(int.Parse(options.GetValueOrDefault("--ttl-seconds", "600")),
                    int.Parse(options.GetValueOrDefault("--slots", "16")));
            else if (action == "close" && !newProfile && options.Keys.All(k => k is "--registry" or "--profiles"))
                result = store.CloseEnrollment();
            else throw new ArgumentException();
            Console.WriteLine(JsonSerializer.Serialize(result, new JsonSerializerOptions(JsonSerializerDefaults.Web))); return 0;
        }
        catch (Exception e)
        {
            Console.WriteLine(JsonSerializer.Serialize(new { status = "refused", errorType = e.GetType().Name })); return 2;
        }
    }
}
