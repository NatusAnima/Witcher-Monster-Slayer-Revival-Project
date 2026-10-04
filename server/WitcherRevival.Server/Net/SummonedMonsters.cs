namespace WitcherRevival.Server.Net;

/// <summary>
/// Summoned monster groups: SummonLocalMonsters (111) creates them, GetSummonedMonsters (112) lists them,
/// EncounterSummonedMonster (113) picks the fought monster and CombatEndSummonedMonster (114) ends that
/// fight. Groups are saved with the point they were summoned at (never logged), so the client can place
/// the living monsters around it again after a restart; it picks the exact spots at random
/// (SpawnPositionLocator.GetOneOfBestFromBuffer). Groups saved by older releases have no point and are
/// not listed until the next summon request supplies it.
/// </summary>
public sealed class SummonedMonsters
{
    public sealed record Monster(int MonsterId, int Difficulty, long InstanceId, bool Alive);

    public sealed record Group(int ItemType, int ItemId, int StartTime, int DespawnTime, int? Longitude, int? Latitude,
        IReadOnlyList<Monster> Monsters);

    private readonly object _gate = new();
    private readonly List<Group> _groups;
    private readonly Action<IReadOnlyList<Group>> _save;
    private long? _encountered;

    /// <param name="saved">Groups restored from the profile.</param>
    /// <param name="save">Receives the groups after every change.</param>
    public SummonedMonsters(IEnumerable<Group>? saved, Action<IReadOnlyList<Group>> save)
    {
        _groups = saved?.ToList() ?? new List<Group>();
        _save = save;
    }

    /// <summary>Returns the active group of this summoning item, or creates one.</summary>
    public Group Summon(int itemType, int itemId, int now, int ttl, int longitude, int latitude,
        IEnumerable<(int MonsterId, int Difficulty)> monsters)
    {
        lock (_gate)
        {
            Expire(now);
            int index = _groups.FindIndex(group => group.ItemType == itemType && group.ItemId == itemId);
            if (index >= 0)
            {
                // A group restored after a restart gets the position of this request back.
                if (_groups[index].Longitude is null)
                {
                    _groups[index] = _groups[index] with { Longitude = longitude, Latitude = latitude };
                    Save();
                }
                return _groups[index];
            }
            // StartTime is one second in the past: the client shows a monster only after its spawn second.
            var created = new Group(itemType, itemId, now - 1, now + ttl, longitude, latitude,
                monsters.Select(m => new Monster(m.MonsterId, m.Difficulty, NewInstanceId(), true)).ToList());
            _groups.Add(created);
            Save();
            return created;
        }
    }

    /// <summary>Active groups whose position is known.</summary>
    public IReadOnlyList<Group> Active(int now)
    {
        lock (_gate)
        {
            Expire(now);
            return _groups.Where(group => group.Longitude is not null).ToList();
        }
    }

    /// <summary>Creates a paid group only when its owner can atomically save the group, item debit and modifier.
    /// A fresh request cannot reuse an active paid group: the client would debit another scroll on success.</summary>
    public Group? TrySummonOwned(int now, int longitude, int latitude, IEnumerable<(int MonsterId, int Difficulty)> monsters,
        Func<Group, IReadOnlyList<Group>, bool> commit)
    {
        lock (_gate)
        {
            Expire(now);
            if (_groups.Any(g => g.ItemType == 16 && g.ItemId == 2)) return null;
            var group = new Group(16, 2, now - 1, now + 499, longitude, latitude,
                monsters.Select(m => new Monster(m.MonsterId, m.Difficulty, NewInstanceId(), true)).ToList());
            if (!commit(group, [.. _groups, group])) return null;
            _groups.Add(group);
            return group;
        }
    }

    /// <summary>Creates at most one aura group, with persistence of its cooldown delegated to one commit.</summary>
    public Group? TrySummonAura(int now, int ttl, int longitude, int latitude,
        (int MonsterId, int Difficulty) monster, Func<Group, IReadOnlyList<Group>, bool> commit)
    {
        lock (_gate)
        {
            // Do not alter memory until the entire cooldown/group transaction has reached disk.
            var active = _groups.Where(g => g.DespawnTime > now).ToList();
            if (active.Any(g => g.ItemType == 13)) return null;
            var group = new Group(13, 29, now - 1, checked(now - 1 + ttl), longitude, latitude,
                [new Monster(monster.MonsterId, monster.Difficulty, NewInstanceId(), true)]);
            active.Add(group);
            if (!commit(group, active)) return null;
            _groups.Clear(); _groups.AddRange(active);
            return group;
        }
    }

    /// <summary>Marks a living monster as the one being fought.</summary>
    public bool Encounter(long instanceId, int now)
    {
        lock (_gate)
        {
            Expire(now);
            bool alive = _groups.SelectMany(group => group.Monsters).Any(m => m.InstanceId == instanceId && m.Alive);
            _encountered = alive ? instanceId : null;
            return alive;
        }
    }

    /// <summary>Ends the current fight. A win marks the monster defeated; returns the fought monster.</summary>
    public Monster? EndEncounter(bool win)
    {
        lock (_gate)
        {
            if (_encountered is not long id) return null;
            _encountered = null;
            for (int i = 0; i < _groups.Count; i++)
            {
                var monster = _groups[i].Monsters.FirstOrDefault(m => m.InstanceId == id && m.Alive);
                if (monster is null) continue;
                if (win)
                {
                    _groups[i] = _groups[i] with
                    {
                        Monsters = _groups[i].Monsters.Select(m => m.InstanceId == id ? m with { Alive = false } : m).ToList(),
                    };
                    Save();
                }
                return monster;
            }
            return null;
        }
    }

    // Caller holds _gate.
    private void Expire(int now)
    {
        if (_groups.RemoveAll(group => group.DespawnTime <= now) > 0) Save();
    }

    private void Save() => _save(_groups.ToList());

    private long NewInstanceId()
    {
        long id;
        do id = Random.Shared.NextInt64(1L << 40, long.MaxValue);
        while (_groups.Any(group => group.Monsters.Any(m => m.InstanceId == id)));
        return id;
    }
}
