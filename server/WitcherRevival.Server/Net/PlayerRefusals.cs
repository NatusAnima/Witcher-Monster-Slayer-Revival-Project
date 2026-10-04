using System.Buffers.Binary;
using WitcherRevival.Server.Protocol;

namespace WitcherRevival.Server.Net;

public sealed partial class PlayerService
{
    private int CurrentEquipment(bool armor)
    {
        var p = profiles.Snapshot().Player;
        return p is null ? 1 : armor ? EquipmentOf(p).Armor : EquipmentOf(p).Sword;
    }

    private int CurrentTrackedQuest(LocalProfileStore.Profile snapshot)
    {
        if (Reconstruction.TutorialNode(snapshot.QuestStage) is { } tutorial) return tutorial.QuestId;
        if (snapshot.QuestStage == LocalProfileStore.JvDoneStage && SeasonOne(snapshot) is { } season)
            return season.Tracked ?? season.Started.LastOrDefault(-1);
        bool joint = QueuedStoryNode(snapshot) is not null || snapshot.QuestStage is
            LocalProfileStore.JointVentureStage or LocalProfileStore.JvObeliskStage or LocalProfileStore.JvGiftsStage;
        return joint ? 146 : 145;
    }

    /// <summary>Verified native failure DTOs, including consumers which ignore Result. The caller preserves
    /// RPC method/request ID. This does not invent a generic error for unverified protocols. Original 1.1.116
    /// factories: Craft 0x247F034, ClaimRecipe 0x247DCE4, Knowledge 0x247D948, AddModifier 0x247C338.
    /// All integers use the protocol's big-endian order, independently of the ARM64 executable endianness.</summary>
    private byte[]? RefusalFor(ApiProtocol.ApiRequest req)
    {
        int arg = req.Data.Length >= 4 ? BinaryPrimitives.ReadInt32BigEndian(req.Data) : 0;
        long brewer = req.Data.Length >= 8 ? BinaryPrimitives.ReadInt64BigEndian(req.Data) : 0;
        byte[] Fields(bool prefix, params int[] values)
        {
            var b = new ByteBuffer(); if (prefix) b.WriteByte(0);
            foreach (int value in values) b.WriteInt(value); return b.ToArray();
        }
        switch (req.Method)
        {
            case >= 103 and <= 108: return SocialService.Refusal(req);
            case M_BuyShopBundle or M_BuyShopInAppBundle:
                return Fields(true, 0, profiles.Snapshot().Player?.Gold ?? 0);
            case M_DistanceTraveled: return BuildIntResponse(false, CurrentDistance());
            case M_TrackQuest: return BuildIntResponse(false, CurrentTrackedQuest(profiles.Snapshot()));
            case M_EquipArmor: return BuildIntResponse(false, CurrentEquipment(true));
            case M_EquipSword or M_EquipSteelSword or M_EquipSilverSword:
                return BuildIntResponse(false, CurrentEquipment(false));
            case M_SetCustomizationHead: return BuildIntResponse(false, 1);
            case M_SetGender: return BuildIntResponse(false, profiles.Snapshot().Player?.Gender ?? 0);
            case M_AcquireSkill: return BuildIntResponse(false, arg);
            // PlayerData and PlayerSkills ignore Success. -1 resolves no monster; zero adds no points.
            case M_ClaimMonsterKnowledgeReward: return Fields(true, -1, 0);
            case M_CraftItem or M_ClaimRecipe:
                var craft = new ByteBuffer(); craft.WriteByte(0); craft.WriteLong(brewer); craft.WriteInt(0);
                if (req.Method == M_CraftItem) { craft.WriteInt(0); craft.WriteInt(0); }
                return craft.ToArray();
            case 47 or 48 or 49 or 50 or 51 or 71 or 100 or 109 or 118: return new byte[9];
            case M_AddPlayerModifier: return Fields(false, 4, 1, 0, 0, 0);
            case M_RemovePlayerModifier: return Fields(false, 1, 0);
            case M_SetName or M_ThrowBomb or M_AddSkillPoints or M_GetTransactionStatus or M_GetLastSummoningSkillUsageTime:
                return BuildIntResponse(false, 0);
            // Summon Factory reads only Result on failure, before the success-only group count.
            case M_SummonLocalMonsters or M_CancelCrafting or M_SetFacts:
            case M_LoadCells or M_PrepareToCombat or M_EncounterMonster or M_BuyAutoEquipItems or M_UseOilPotions:
                return new byte[1];
            case M_RelocateQuest: return new byte[13];
            default: return null;
        }
    }
}
