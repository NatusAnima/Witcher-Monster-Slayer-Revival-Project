using System.Security.Cryptography;

namespace WitcherRevival.Server.Net;

/// <summary>One immutable wire catalogue per process, shared by HTTP and TCP bootstrap.</summary>
public sealed class StaticDataSnapshot
{
    public byte[] Gzip { get; }
    public string Revision { get; }
    public string Url { get; }

    public StaticDataSnapshot(IConfiguration cfg, DrivingWarningSettings driving, TaskCatalog tasks)
    {
        // TaskCatalog refuses changes to the live wire catalogue. Draw weights and minimum levels
        // remain live server decisions and do not alter this serialized representation.
        Gzip = PreloaderStaticData.GzipContainer(cfg.GetValue("Preloader:EmptyObject", false),
            driving, tasks.Current, SkillBalancePolicy.FromConfiguration(cfg));
        Revision = Convert.ToHexString(SHA256.HashData(Gzip)).ToLowerInvariant();
        string? publicUrl = cfg["Http:StaticDataUrl"];
        if (publicUrl is not null)
        {
            if (!Uri.TryCreate(publicUrl, UriKind.Absolute, out var uri) || uri.Scheme != "https" ||
                !string.IsNullOrEmpty(uri.UserInfo) || !string.IsNullOrEmpty(uri.Query) ||
                !string.IsNullOrEmpty(uri.Fragment) || uri.AbsolutePath != "/staticdata")
                throw new InvalidOperationException("Http:StaticDataUrl must be an HTTPS /staticdata URL without credentials, query or fragment.");
            Url = uri.AbsoluteUri;
        }
        else
        {
            string host = System.Net.IPAddress.TryParse(cfg["Http:AdvertisedHost"], out var ip) ? ip.ToString() : "127.0.0.1";
            if (host.Contains(':')) host = "[" + host + "]";
            Url = $"http://{host}:{cfg.GetValue("Http:Port", 8080)}/staticdata";
        }
    }
}
