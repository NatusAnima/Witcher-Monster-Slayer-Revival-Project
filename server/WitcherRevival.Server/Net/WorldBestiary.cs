using System.Text.Json;

namespace WitcherRevival.Server.Net;

/// <summary>
/// Every monster the world may spawn (Story/world-bestiary.json, built by server/story-1.1.116/world_bestiary.py).
///
/// Client: the 1.1.116 APK ships 139 monsters with a map model, a presentation, a settings asset (with its trophy
/// address) and bestiary texts. INFO_1 of the texts names the family and INFO_2 the occurrences
/// (MONSTERS/OCCURANCE/*), which <see cref="WorldSpawns"/> uses as spawn rules. Community (M01): rarity, skulls
/// and vulnerabilities, matched by the client's English name. Rows 1-36 are the server's existing ones; the file
/// adds rows from id 101 for the other monsters. Left out are the fight targets whose graphs attach their settings
/// themselves (the training dummies, the human story actors, the quest golem) and the cursed Liho, a quest POI
/// without bestiary texts.
/// </summary>
public static class WorldBestiary
{
    /// <summary>A species: its monsters row, name, family (monster_families id), the sheet's rarity (1 common,
    /// 2 rare, 3 legendary) and skulls, the row's difficulty tier and the client's occurrence tags.</summary>
    public sealed record Species(int MonsterId, string Slug, string Name, int Family, int Rarity, int Skulls,
        int Difficulty, string[] Tags);

    private sealed record Data(List<Species> Species, List<JsonElement> Monsters, Dictionary<string, int[]> Vulnerabilities);

    private static readonly JsonSerializerOptions Options = new() { PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower };

    /// <summary>The bestiary file as shipped (also served to the local tests).</summary>
    public static readonly string Json = LoadJson();

    private static readonly Data Bestiary = JsonSerializer.Deserialize<Data>(Json, Options)
        ?? throw new InvalidDataException("Empty world bestiary.");

    private static readonly Dictionary<int, Species> ById = Bestiary.Species.ToDictionary(s => s.MonsterId);

    public static IReadOnlyList<Species> All => Bestiary.Species;
    public static IReadOnlyDictionary<string, int[]> Vulnerabilities => Bestiary.Vulnerabilities;
    public static IEnumerable<string> MonsterRows => Bestiary.Monsters.Select(row => JsonSerializer.Serialize(row));

    /// <summary>The species of a world monster row, or null for rows that are not world species.</summary>
    public static Species? Of(int monsterId) => ById.GetValueOrDefault(monsterId);

    /// <summary>The family of a world monster (client bestiary), or null for story actors.</summary>
    public static int? FamilyOf(int monsterId) => ById.TryGetValue(monsterId, out var species) ? species.Family : null;

    private static string LoadJson()
    {
        using var stream = typeof(WorldBestiary).Assembly.GetManifestResourceStream("world-bestiary.json")
            ?? throw new InvalidDataException("The world bestiary resource is missing.");
        using var reader = new StreamReader(stream);
        return reader.ReadToEnd();
    }
}
