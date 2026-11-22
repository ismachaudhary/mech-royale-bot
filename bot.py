#!/usr/bin/env python3
"""Mech Royale V2: zone-aware movement, target lead, and weapon-aware combat."""
import math
import mechfight as mf


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def norm(x, y):
    d = math.hypot(x, y)
    return [x / d, y / d] if d > 1e-8 else [0.0, 0.0]


def dist2(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def get_weapon(me, slot):
    ws = me.get("weapons") or []
    return ws[slot] if slot < len(ws) else None



class Bot:
    name = "ZoneHunter-v2"



    def __init__(self, hello):
        self.config = hello.get("config", {})
        self.pickup_radius = self.config.get("loot", {}).get("pickup_radius", 4.0)
        self.gun_cfg = self.config.get("weapons", {}).get("gun", {})
        self.laser_cfg = self.config.get("weapons", {}).get("laser", {})
        self.lightning_cfg = self.config.get("weapons", {}).get("lightning", {})
        self.mortar_cfg = self.config.get("weapons", {}).get("mortar", {})

    def choose_target(self, obs, me):
        p = me.get("pos", [0, 0, 0])
        enemies = [e for e in obs.get("mechs", []) if e.get("kind") == "mech"]
        if not enemies:
            return None
        def rank(e):
            ep = e.get("pos", [0, 0, 0])
            d = math.hypot(ep[0] - p[0], ep[1] - p[1])
            hp = e.get("hp", 1000)
            # Nearby enemies are easier to hit; lower HP makes a finishing target attractive.
            return d + 0.025 * hp - min(e.get("cubes", 0), 10) * 2
        return min(enemies, key=rank)



    def movement(self, obs, me, target):
        pos = me.get("pos", [0, 0, 0])
        zone = obs.get("zone", {})
        center = zone.get("center", [0, 0])
        next_center = zone.get("next_center", center)
        radius = zone.get("radius", 500)
        dx, dy = center[0] - pos[0], center[1] - pos[1]
        dcenter = math.hypot(dx, dy)
        inward = norm(dx, dy)
        future = norm(next_center[0] - pos[0], next_center[1] - pos[1])

        # Get well inside the current ring; move toward the next ring as it closes.
        if dcenter > radius - 28:
            move = inward
            boost = dcenter > radius - 5
        else:
            # Orbit while drifting toward the next circle's center.
            sign = 1 if (int(me.get("id", 0)) % 2 == 0) else -1
            tangent = [-sign * inward[1], sign * inward[0]]
            move = norm(0.25 * inward[0] + 0.65 * tangent[0] + 0.35 * future[0],
                       0.25 * inward[1] + 0.65 * tangent[1] + 0.35 * future[1])
            boost = False


        # If an enemy is dangerously close, retreat diagonally rather than freeze.
        if target:
            tp = target.get("pos", [0, 0, 0])
            d = dist2(pos, tp)
            if d < 24:
                away = norm(pos[0] - tp[0], pos[1] - tp[1])
                tangent = [-away[1], away[0]]
                retreat = norm(0.75 * away[0] + 0.45 * tangent[0],
                             0.75 * away[1] + 0.45 * tangent[1])
                # Keep zone correction dominant if close to the boundary.
                if dcenter > radius - 50:
                    move = norm(0.65 * inward[0] + 0.35 * retreat[0],
                               0.65 * inward[1] + 0.35 * retreat[1])
                else:
                    move = retreat
                boost = d < 14 and me.get("energy", 0) > 20
        return move, boost



    def aim_at(self, me, target, lead_s=0.0):
        pos = me.get("pos", [0, 0, 0])
        tp = target.get("pos", [0, 0, 0])
        tv = target.get("vel", [0, 0, 0])
        own_muzzle = me.get("stats", {}).get("muzzle_height", 7.0)
        target_height = 4.5 * (1.0 + 0.05 * min(target.get("cubes", 0), 10))
        tx = tp[0] + tv[0] * lead_s - pos[0]
        ty = tp[1] + tv[1] * lead_s - pos[1]
        tz = tp[2] + tv[2] * lead_s + target_height - (pos[2] + own_muzzle)
        horizontal = max(0.1, math.hypot(tx, ty))
        return [math.atan2(ty, tx), clamp(math.atan2(tz, horizontal), -0.7, 1.25)], horizontal



    def upgrade_pick(self, offer, me):
        choices = (offer or {}).get("choices", [])
        if not choices:
            return None
        # Favor broad survivability and reliable weapon upgrades.
        preference = ["armor", "regen", "health", "gun_rate", "damage", "sensors", "gun_damage", "gun_spread"]
        scores = []
        for choice in choices:
            cid = str(choice.get("id", "")).lower()
            name = str(choice.get("name", "")).lower()
            desc = str(choice.get("desc", "")).lower()
            text = " ".join([cid, name, desc])
            score = 0
            if "armor" in text or "damage taken" in text: score += 10
            if "regen" in text or "health" in text or "heal" in text: score += 8
            if "gun" in text and ("rate" in text or "fire" in text or "damage" in text): score += 7
            if "sensor" in text or "vision" in text: score += 4
            if "damage" in text and "taken" not in text: score += 6
            if "mortar" in text and get_weapon(me, 1) and get_weapon(me, 1).get("kind") == "mortar": score += 3
            if "laser" in text and get_weapon(me, 1) and get_weapon(me, 1).get("kind") == "laser": score += 3
            if "lightning" in text and get_weapon(me, 1) and get_weapon(me, 1).get("kind") == "lightning": score += 3
            scores.append(score)
        return max(range(len(scores)), key=lambda i: scores[i])



    def act(self, obs):
        me = obs.get("self", {})
        pos = me.get("pos", [0, 0, 0])
        tick = obs.get("tick", 0)
        target = self.choose_target(obs, me)
        move, boost = self.movement(obs, me, target)
        aim = me.get("aim", [0.0, 0.0])
        fire = [False, False]
        reload_gun = False
        gun = get_weapon(me, 0)
        special = get_weapon(me, 1)
        target_dist = 9999


        if target:
            # Lead gun target using straight-line projectile travel time.
            tp = target.get("pos", [0, 0, 0])
            d = dist2(pos, tp)
            speed = max(1.0, (gun or {}).get("stats", {}).get("speed", self.gun_cfg.get("speed", 252)))
            travel = min(1.25, d / speed)
            aim, target_dist = self.aim_at(me, target, travel)
            gun_range = (gun or {}).get("stats", {}).get("range", self.gun_cfg.get("range", 230))
            if gun and gun.get("kind") == "gun" and d <= gun_range:
                if gun.get("reload", 0) > 0:
                    fire[0] = False
                elif gun.get("ammo", 0) <= 0:
                    reload_gun = True
                else:
                    fire[0] = True
            # Secondary weapons: use each weapon's own engagement envelope.
            if special:
                kind = special.get("kind")
                if kind == "lightning" and d <= self.lightning_cfg.get("range", 45) and me.get("energy", 0) >= self.lightning_cfg.get("energy", 3):
                    fire[1] = True
                elif kind == "laser" and d <= self.laser_cfg.get("range", 280):
                    charge = special.get("charge", 0)
                    # Hold to charge; release after ~0.6s for a strong shot.
                    fire[1] = charge < min(0.62, self.laser_cfg.get("charge", 0.75))
                elif kind == "mortar" and d <= self.mortar_cfg.get("range", 235):
                    # Basic direct-angle mortar shot; upgraded ballistic targeting later.
                    fire[1] = d < 100

        else:
            # No visible target: look toward the next zone to avoid tunnel vision.
            nc = obs.get("zone", {}).get("next_center", [pos[0], pos[1]])
            aim = [math.atan2(nc[1] - pos[1], nc[0] - pos[0]), 0.0]

        # Weapon pickup: when slot 1 is empty, walk toward useful loot.
        if special is None:
            desired_kinds = {"laser", "lightning", "mortar"}
            pickups = [p for p in obs.get("pickups", []) if p.get("kind") in desired_kinds]
            if pickups:
                nearest = min(pickups, key=lambda p: dist2(pos, p.get("pos", [0, 0, 0])))
                pd = dist2(pos, nearest.get("pos", [0, 0, 0]))
                if pd <= self.pickup_radius and abs(nearest["pos"][2] - pos[2]) <= 4:
                    # Prefer lightning for close fights, laser for general range; skip mortar for now.
                    if nearest.get("kind") in ("laser", "lightning"):
                        action_take = nearest.get("id")
                    else:
                        action_take = None
                else:
                    action_take = None
                if pd > self.pickup_radius:
                    # Don't chase loot out of the zone; only modestly bend our path to it.
                    zone_center = obs.get("zone", {}).get("center", [0, 0])
                    zd = dist2(pos, zone_center)
                    zr = obs.get("zone", {}).get("radius", 9999)
                    if zd < zr - 45 and pd < 55:
                        to_pick = norm(nearest["pos"][0] - pos[0], nearest["pos"][1] - pos[1])
                        move = norm(0.65 * move[0] + 0.5 * to_pick[0], 0.65 * move[1] + 0.5 * to_pick[1])
            else:
                action_take = None
        else:
            action_take = None


        pick = self.upgrade_pick(obs.get("offer"), me)
        action = {
            "tick": tick,
            "move": move,
            "boost": bool(boost),
            "jump": bool(me.get("grounded", False) and not me.get("in_zone", True) and tick % 8 == 0),
            "aim": aim,
            "fire": fire,
            "reload": reload_gun,
        }
        if action_take is not None:
            action["take"] = action_take
        if pick is not None:
            action["pick"] = pick
        return action



mf.run(Bot)
