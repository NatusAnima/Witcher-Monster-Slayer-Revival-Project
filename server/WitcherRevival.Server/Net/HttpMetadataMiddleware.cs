namespace WitcherRevival.Server.Net;

/// <summary>Constant endpoint labels, never request URLs or client-supplied values.</summary>
public sealed record LocalHttpEndpoint(string Name);

public sealed class HttpMetadataMiddleware(RequestDelegate next, ILogger<HttpMetadataMiddleware> log)
{
    public async Task InvokeAsync(HttpContext context)
    {
        string failureType = "none";
        try { await next(context); }
        catch (Exception ex)
        {
            failureType = ex.GetType().Name;
            throw;
        }
        finally
        {
            string route = context.GetEndpoint()?.Metadata.GetMetadata<LocalHttpEndpoint>()?.Name ?? "unmatched";
            string method = context.Request.Method switch { "GET" => "GET", "HEAD" => "HEAD", _ => "OTHER" };
            int status = failureType == "none" ? context.Response.StatusCode : 500;
            log.LogInformation("HTTP route={Route} method={Method} status={Status} response_bytes={Bytes} error_type={ErrorType}",
                route, method, status, context.Response.ContentLength ?? -1, failureType);
        }
    }
}
