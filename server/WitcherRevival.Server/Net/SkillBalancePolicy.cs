namespace WitcherRevival.Server.Net;

/// <summary>Explicit reconstruction choices where original 1.1.116 server values were not recovered.
/// These defaults are authored balance, not historical measurements. The dashboard's Tuning page changes them (skills.*,
/// checked there); a server restart and fresh client catalogue load are required after changing them.</summary>
public sealed record SkillBalancePolicy(
    int ExtraPotionChancePercent = 10,
    int SquallElementalRemains = 1,
    int ResolveFloorPercentPerRank = 10,
    int AttackAdrenalineBonus = 1,
    int EventAdrenalineGain = 1,
    int InitialAdrenalineGain = 3,
    int FinalBlowSurvivalChancePercent = 10,
    int InstantSignRecoveryChancePercent = 10,
    int BombAngleReductionDegrees = 15,
    int WitcherAuraIntervalSeconds = 3600,
    int WitcherAuraLifetimeSeconds = 3600,
    int QuenAbsorbPercent = 100)
{
    public static SkillBalancePolicy Default { get; } = new();

    /// <summary>The policy of this server's start (WorldTuning.Started).</summary>
    public static SkillBalancePolicy FromTuning()
    {
        int Value(string key) => (int)WorldTuning.Started[key];
        return new SkillBalancePolicy(
            Value(WorldTuning.ExtraPotionChance),
            Value(WorldTuning.SquallRemains),
            Value(WorldTuning.ResolveFloor),
            Value(WorldTuning.AttackAdrenaline),
            Value(WorldTuning.EventAdrenaline),
            Value(WorldTuning.InitialAdrenaline),
            Value(WorldTuning.SurvivalChance),
            Value(WorldTuning.SignRecoveryChance),
            Value(WorldTuning.BombAngle),
            // August 2021 player reports describe one hourly aura monster lasting one hour.
            // These configurable defaults are reconstruction policy, not recovered server data.
            Value(WorldTuning.AuraInterval) * 60,
            Value(WorldTuning.AuraLifetime) * 60,
            Value(WorldTuning.QuenAbsorb));
    }

    // Roll once while starting a craft, in the same profile transaction as ingredient consumption.
    // The saved quantity survives skill/config changes, retries and process restarts.
    public int CraftOutputCount(LocalProfileStore.PlayerState player, Economy.Recipe recipe) =>
        recipe.ItemType == Economy.TypePotion && player.Skills.Contains(63) &&
        System.Security.Cryptography.RandomNumberGenerator.GetInt32(100) < ExtraPotionChancePercent ? 2 : 1;
}
