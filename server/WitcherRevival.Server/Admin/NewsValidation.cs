using System.Text.Json;
using WitcherRevival.Server.Net;

namespace WitcherRevival.Server.Admin;

public sealed partial class AdminServer
{
    // Return stable field paths and codes, never JSON exception text or authored content.
    private async Task<IResult> WriteNews(string language, HttpRequest request)
    {
        CheckLanguage(language);
        DocumentWrite write;
        try { write = await Body<DocumentWrite>(request); }
        catch (Exception e) when (e is JsonException or InvalidDataException)
        { return NewsRefused([new("document", "write_schema")]); }
        catch (Refusal e) when (e.Status == 413)
        { return NewsRefused([new("document", "feed_size")]); }
        var issues = NewsSchemaIssues(write.Document);
        if (issues.Count != 0) return NewsRefused(issues);
        var feed = write.Document.Deserialize<NewsContainer>(Json)!;
        issues.AddRange(NewsFeed.ValidationIssues(feed));
        for (int i = 0; i < feed.NewsList.Length; i++)
        {
            string? name = feed.NewsList[i]?.ImageUrl;
            if (name is not null && ImageName.IsMatch(name) && name != NewsFeed.DefaultImage &&
                !File.Exists(Path.Combine(newsRoot, "images", name)))
                issues.Add(new($"news_list[{i}].image_url", "image_missing"));
        }
        if (issues.Count != 0) return NewsRefused(issues);
        byte[] bytes = JsonSerializer.SerializeToUtf8Bytes(feed, Json);
        if (bytes.Length > 1024 * 1024) return NewsRefused([new("document", "feed_size")]);
        return SaveDocument(Path.Combine(newsRoot, language + ".json"), write.Revision,
            bytes, "news", language,
            "The next opening of What's new loads this feed.");
    }

    private static IResult NewsRefused(IEnumerable<NewsFeed.ValidationIssue> issues) =>
        Results.Json(new { error = "news_validation", fields = issues.Take(100).ToArray() }, statusCode: 400);

    private static List<NewsFeed.ValidationIssue> NewsSchemaIssues(JsonElement document)
    {
        var issues = new List<NewsFeed.ValidationIssue>();
        bool Shape(JsonElement value, string path, Dictionary<string, JsonValueKind> fields)
        {
            if (value.ValueKind != JsonValueKind.Object)
            { issues.Add(new(path, "object_required")); return false; }
            var seen = new HashSet<string>();
            foreach (var property in value.EnumerateObject())
                if (!fields.ContainsKey(property.Name) || !seen.Add(property.Name))
                    issues.Add(new(path, "unexpected_field"));
            foreach (var field in fields)
                if (!value.TryGetProperty(field.Key, out var property) || property.ValueKind != field.Value ||
                    field.Value == JsonValueKind.Number && !property.TryGetInt32(out _))
                    issues.Add(new(path.Length == 0 ? field.Key : path + "." + field.Key,
                        field.Value == JsonValueKind.Number ? "integer_required" :
                        field.Value == JsonValueKind.Array ? "list_limit" : "text_required"));
            return true;
        }
        if (!Shape(document, "", new() { ["news_list"] = JsonValueKind.Array, ["featured"] = JsonValueKind.Number })) return issues;
        if (!document.TryGetProperty("news_list", out var list) || list.ValueKind != JsonValueKind.Array) return issues;
        if (list.GetArrayLength() > 100) { issues.Add(new("news_list", "list_limit")); return issues; }
        int index = 0;
        foreach (var item in list.EnumerateArray())
        {
            Shape(item, $"news_list[{index++}]", new() {
                ["id"] = JsonValueKind.Number, ["group_id"] = JsonValueKind.String,
                ["title"] = JsonValueKind.String, ["short_description"] = JsonValueKind.String,
                ["date"] = JsonValueKind.String, ["image_url"] = JsonValueKind.String,
                ["content"] = JsonValueKind.String });
        }
        return issues;
    }
}
