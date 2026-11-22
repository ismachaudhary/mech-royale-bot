#!/usr/bin/env python3
"""Zone-first Mech Royale bot V3: prioritize placement, smart retreats, and clean aim."""
import math
import mechfight as mf


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def norm(x, y):
    d = math.hypot(x, y)
    return [x / d, y / d] if d > 1e-8 else [0.0, 0.0]


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def weapon(me, slot):
    ws = me.get("weapons") or []
    return ws[slot] if slot < len(ws) else None



class Bot:
    name = "ZoneSurvivor-v3"



    def __init__(self, hello):
        self.config = hello.get("config", {})
        self.pickup_radius = self.config.get("loot", {}).get("pickup_radius", 4.0)
        self.gun_cfg = self.config.get("weapons", {}).get("gun", {})
        self.laser_cfg = self.config.get("weapons", {}).get("laser", {})
        self.lightning_cfg = self.config.get("weapons", {}).get("lightning", {})
        self.mortar_cfg = self.config.get("weapons", {}).get("mortar", {})

    def target(self, obs, me):
        pos = me.get("pos", [0, 0, 0])
        candidates = [e for e in obs.get("mechs", []) if e.get("kind") == "mech"]
        if not candidates:
            return None
        def score(e):
            ep = e.get("pos", [0, 0, 0])
            d = dist(pos, ep)
            hp = e.get("hp", e.get("max_hp", 1400))
            cubes = e.get("cubes", 0)
            # Favor threats we can reach and finish, but don't chase far-away targets.
            return d + 0.012 * hp - min(cubes, 8) * 1.8
        return min(candidates, key=score)



    def move(self, obs, me, target):
        pos = me.get("pos", [0, 0, 0])
        zone = obs.get("zone", {})
        center = zone.get("center", [pos[0], pos[1]])
        next_center = zone.get("next_center", center)
        radius = zone.get("radius", 500)
        to_center = norm(center[0] - pos[0], center[1] - pos[1])
        to_future = norm(next_center[0] - pos[0], next_center[1] - pos[1])
        d_now = dist(pos, center)
        d_future = dist(pos, next_center)

        # Stay well inside the current zone; bias toward the next circle early.
        if d_now > radius - 65:
            move = norm(0.8 * to_center[0] + 0.2 * to_future[0],
                       0.8 * to_center[1] + 0.2 * to_future[1])
            boost = d_now > radius - 18 and me.get("energy", 0) > 12
        else:
            # Avoid the shrinking boundary; gently migrate to next center.
            if d_future > max(30, zone.get("next_radius", radius) * 0.58):
                move = norm(0.82 * to_future[0] + 0.18 * to_center[0],
                           0.82 * to_future[1] + 0.18 * to_center[1])
            else:
                # Small circling movement keeps us moving without wandering to the rim.
                inward = to_future if d_future > 1 else to_center
                sign = 1 if int(me.get("id", 0)) % 2 == 0 else -1
                tangent = [-sign * inward[1], sign * inward[0]]
                move = norm(0.70 * inward[0] + 0.30 * tangent[0],
                           0.70 * inward[1] + 0.30 * tangent[1])
            boost = False


        # Emergency retreat, blended with zone movement if we're near the rim.
        if target:
            tp = target.get("pos", [0, 0, 0])
            enemy_d = dist(pos, tp)
            if enemy_d < 38:
                away = norm(pos[0] - tp[0], pos[1] - tp[1])
                if d_now > radius - 85:
                    move = norm(0.75 * to_center[0] + 0.25 * away[0],
                               0.75 * to_center[1] + 0.25 * away[1])
                else:
                    move = norm(0.78 * away[0] + 0.22 * to_future[0],
                               0.78 * away[1] + 0.22 * to_future[1])
                boost = enemy_d < 24 and me.get("energy", 0) > 20
        return move, boost



    def aim(self, me, target, lead=0.0):
        pos = me.get("pos", [0, 0, 0])
        tp = target.get("pos", [0, 0, 0])
        tv = target.get("vel", [0, 0, 0])
        muzzle = me.get("stats", {}).get("muzzle_height", 7.0)
        th = 4.5 * (1.0 + 0.05 * min(target.get("cubes", 0), 10))
        x = tp[0] + tv[0] * lead - pos[0]
        y = tp[1] + tv[1] * lead - pos[1]
        z = tp[2] + tv[2] * lead + th - (pos[2] + muzzle)
        h = max(0.1, math.hypot(x, y))
        return [math.atan2(y, x), clamp(math.atan2(z, h), -0.7, 1.25)], h
    def upgrades(self, offer, me):
        choices = (offer or {}).get("choices", [])
        if not choices:
            return None
        best, best_score = 0, -999
        for i, c in enumerate(choices):
            text = (str(c.get("id", "")) + " " + str(c.get("name", "")) + " " + str(c.get("desc", "")) ).lower()
            s = 0
            if "armor" in text or "damage taken" in text: s += 14
            if "regen" in text or "health" in text or "heal" in text or "hp" in text: s += 13
            if "energy" in text: s += 8
            if "speed" in text or "mobility" in text or "boost" in text: s += 8
            if "gun" in text and ("rate" in text or "fire" in text): s += 8
            if "damage" in text and "taken" not in text: s += 7
            if "sensor" in text or "vision" in text: s += 6
            if "laser" in text and weapon(me, 1) and weapon(me, 1).get("kind") == "laser": s += 4
            if "lightning" in text and weapon(me, 1) and weapon(me, 1).get("kind") == "lightning": s += 4
            if s > best_score:
                best, best_score = i, s
        return best



    def act(self, obs):
        me = obs.get("self", {})
        pos = me.get("pos", [0, 0, 0])
        tick = obs.get("tick", 0)
        target = self.target(obs, me)
        move, boost = self.move(obs, me, target)
        gun = weapon(me, 0)
        special = weapon(me, 1)
        fire = [False, False]
        reload_gun = False
        aim = me.get("aim", [0.0, 0.0])
        d = 9999

        if target:
            tp = target.get("pos", [0, 0, 0])
            d = dist(pos, tp)
            speed = max(1.0, (gun or {}).get("stats", {}).get("speed", self.gun_cfg.get("speed", 252)))
            gun_lead = min(1.0, d / speed)
            aim, _ = self.aim(me, target, gun_lead)
            gun_range = (gun or {}).get("stats", {}).get("range", self.gun_cfg.get("range", 230))
            if gun and gun.get("kind") == "gun" and d <= gun_range:
                if gun.get("ammo", 0) <= 0:
                    reload_gun = gun.get("reload", 0) <= 0
                else:
                    fire[0] = True
            if special:
                kind = special.get("kind")
                if kind == "laser" and d <= self.laser_cfg.get("range", 280):
                    charge = special.get("charge", 0)
                    # Release at high charge; start charging again after cooldown.
                    fire[1] = charge < min(0.66, self.laser_cfg.get("charge", 0.75))
                    aim, _ = self.aim(me, target, 0.15 if charge > 0 else 0.0)
                elif kind == "lightning" and d <= self.lightning_cfg.get("range", 45) and me.get("energy", 0) >= self.lightning_cfg.get("energy", 3):
                    fire[1] = True
                    aim, _ = self.aim(me, target, 0.0)
                elif kind == "mortar" and 55 < d <= self.mortar_cfg.get("range", 235):
                    # Low-arc ballistic angle; avoid close splash damage.
                    v = self.mortar_cfg.get("speed", 72)
                    g = self.mortar_cfg.get("gravity", 22)
                    ratio = clamp(g * d / max(1.0, v * v), 0.0, 0.98)
                    pitch = 0.5 * math.asin(ratio)
                    aim, _ = self.aim(me, target, 0.0)
                    aim[1] = clamp(pitch, -0.7, 1.25)
                    fire[1] = True
        else:
            # Sweep the torso to search for targets; incorporate fresh sounds.
            sounds = obs.get("sounds", [])
            near_sound = None
            for s in sounds:
                if s.get("age", 9) <= 1.0 and s.get("dist") in ("near", "mid"):
                    if near_sound is None or s.get("age", 9) < near_sound.get("age", 9):
                        near_sound = s
            if near_sound:
                aim = [near_sound.get("bearing", aim[0]), 0.0]
            else:
                aim = [((tick * 0.14 + (int(me.get("id", 0)) * 1.7)) % (2 * math.pi)) - math.pi, 0.0]

        # Face the last reported attacker briefly: front armor reduces damage.
        for event in reversed(obs.get("events", [])):
            if event.get("type") == "damaged" and event.get("bearing") is not None:
                if not target or d > 42:
                    aim = [event["bearing"], 0.0]
                break

        take = None
        if special is None:
            pickups = [p for p in obs.get("pickups", []) if p.get("kind") in ("laser", "lightning")]
            if pickups:
                pick = min(pickups, key=lambda p: dist(pos, p.get("pos", [0,0,0])))
                pd = dist(pos, pick.get("pos", [0,0,0]))
                if pd <= self.pickup_radius and abs(pick.get("pos", [0,0,0])[2] - pos[2]) <= 4:
                    take = pick.get("id")
                elif pd < 38 and dist(pos, obs.get("zone", {}).get("center", pos)) < obs.get("zone", {}).get("radius", 500) - 70:
                    toward = norm(pick["pos"][0] - pos[0], pick["pos"][1] - pos[1])
                    move = norm(0.72 * move[0] + 0.28 * toward[0], 0.72 * move[1] + 0.28 * toward[1])

        # Jump out of damage/edge traps occasionally, never jump just for animation.
        jump = bool(me.get("grounded", False) and (not me.get("in_zone", True)) and tick % 4 == 0)
        pick_upgrade = self.upgrades(obs.get("offer"), me)
        action = {"tick": tick, "move": move, "boost": bool(boost), "jump": jump,
                  "aim": aim, "fire": fire, "reload": reload_gun}
        if take is not None:
            action["take"] = take
        if pick_upgrade is not None:
            action["pick"] = pick_upgrade
        return action



mf.run(Bot)
