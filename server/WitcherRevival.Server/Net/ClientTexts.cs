namespace WitcherRevival.Server.Net;

/// <summary>
/// The texts hook.js gives the game (its "texts" stage fetches GET /revival/texts once at start and answers
/// I2.Loc.LocalizationManager.GetTranslation with them), following the dashboard's settings: a monster's bestiary
/// "Occurrence" line when the wiki's tags are in use (built from the game's own phrases, so it stays translated), each
/// trinket's bonus line and attack modifier name while trinket bonuses are on, and the weather items' names (they reuse
/// the icons of unused consumables, whose own texts they replace). Other texts are English in every language.
/// </summary>
public static class ClientTexts
{
    private static readonly IReadOnlyDictionary<int, (string Name, string Description)> WeatherItems = new Dictionary<int, (string, string)>
    {
        [Consumables.Rain] = ("Rain Charm", "Brings rain where you are for an hour. Monsters that like rain come out " +
            "(drowners, arachases, archespores…) and even leave the water, and the Squall potion works. Monsters already out " +
            "stay until they leave."),
        [Consumables.Fog] = ("Fog Charm", "Brings fog where you are for an hour, and the monsters that like it come out " +
            "(foglets, wererats, d'jinni…). Monsters already out stay until they leave."),
        [Consumables.Clear] = ("Sun Charm", "Clears the sky where you are for an hour. Monsters already out stay until they leave."),
    };

    /// <summary>The INFO_2 line of a monster's bestiary entry for [tags], as the client writes it (term references).</summary>
    public static string OccurrenceLine(IEnumerable<string> tags) =>
        "[0{**UI/PANELS/BESTIARY/OCCURANCE**}0]: " + string.Concat(tags.Select(tag => $"**MONSTERS/OCCURANCE/{tag}**\n"));

    public static object Build()
    {
        var replace = new Dictionary<string, string>();
        var append = new Dictionary<string, string>();
        if (WorldTuning.Current.On(WorldTuning.WikiOccurrences))
            foreach (var species in WorldBestiary.All.Where(s => s.ClientTags is { } client && !client.SequenceEqual(s.Tags)))
                replace[$"MONSTERS/DESCRIPTIONS/{species.Slug.ToUpperInvariant()}/INFO_2"] = OccurrenceLine(species.Tags);
        if (WorldTuning.Current.On(WorldTuning.TrinketBuffs))
        {
            foreach (var (term, text) in TrinketBuffs.Texts()) append[term] = text;
            foreach (var (term, text) in TrinketBuffs.ModifierNames()) replace[term] = text;
        }
        foreach (var item in Consumables.All.Where(c => c.Weather is not null))
        {
            var (name, description) = WeatherItems[item.Id];
            replace[$"ITEMS/NAMES/CONSUMABLES/{item.Slug.ToUpperInvariant()}"] = name;
            replace[$"ITEMS/DESCRIPTIONS/CONSUMABLES/{item.Slug.ToUpperInvariant()}"] = description;
            replace[$"NOTIFICATIONS/EFFECT/{item.ModifierSlug.ToUpperInvariant()}"] = name;
        }
        return new { replace, append };
    }
}
