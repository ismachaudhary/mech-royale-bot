#!/usr/bin/env python3
import math
import mechfight as mf

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def norm(x, y):
    d = math.hypot(x, y)
    return [x / d, y / d] if d > 1e-8 else [0.0, 0.0]

def dist(a, b):
    return math.hypot(a[0]-b[0], a[1]-b[1])

def get_weapon(me, slot):
    ws = me.get("weapons") or []
    return ws[slot] if slot < len(ws) else None

class Bot:
    name = "ZoneLoot-V4"

    def __init__(self, hello):
        self.cfg = hello.get("config", {})
        self.gun_cfg = self.cfg.get("weapons", {}).get("gun", {})
        self.laser_cfg = self.cfg.get("weapons", {}).get("laser", {})
        self.lightning_cfg = self.cfg.get("weapons", {}).get("lightning", {})
        self.mortar_cfg = self.cfg.get("weapons", {}).get("mortar", {})
        self.pickup_radius = self.cfg.get("loot", {}).get("pickup_radius", 4)

    def target(self, obs, me):
        pos = me.get("pos", [0,0,0])
        enemies = [e for e in obs.get("mechs", [])
                   if e.get("kind") == "mech" and e.get("id") != me.get("id")]
        if not enemies:
            return None

        def score(e):
            ep = e.get("pos", [0,0,0])
            d = dist(pos, ep)
            hp = e.get("hp", 1400)
            cubes = e.get("cubes", 0)
            return d + 0.010*hp - min(cubes, 10)*2

        return min(enemies, key=score)

    def aim_at(self, me, target, lead=0.0):
        pos = me.get("pos", [0,0,0])
        tp = target.get("pos", [0,0,0])
        tv = target.get("vel", [0,0,0])
        muzzle = me.get("stats", {}).get("muzzle_height", 7)
        height = 4.5
        x = tp[0] + tv[0]*lead - pos[0]
        y = tp[1] + tv[1]*lead - pos[1]
        z = tp[2] + tv[2]*lead + height - (pos[2]+muzzle)
        h = max(0.1, math.hypot(x,y))
        return [math.atan2(y,x), clamp(math.atan2(z,h), -0.7, 1.25)], h

    def zone_move(self, obs, me):
        pos = me.get("pos", [0,0,0])
        zone = obs.get("zone", {})
        center = zone.get("center", pos)
        next_center = zone.get("next_center", center)
        radius = zone.get("radius", 500)
        d = dist(pos, center)
        dn = dist(pos, next_center)

        to_center = norm(center[0]-pos[0], center[1]-pos[1])
        to_next = norm(next_center[0]-pos[0], next_center[1]-pos[1])

        if d > radius-90:
            move = norm(0.85*to_center[0]+0.15*to_next[0],
                       0.85*to_center[1]+0.15*to_next[1])
            boost = d > radius-30 and me.get("energy",0) > 15
        elif dn > zone.get("next_radius", radius)*0.65:
            move = norm(0.8*to_next[0]+0.2*to_center[0],
                       0.8*to_next[1]+0.2*to_center[1])
            boost = False
        else:
            # Gentle movement toward a safe interior point.
            move = norm(0.65*to_next[0]+0.35*to_center[0],
                       0.65*to_next[1]+0.35*to_center[1])
            boost = False
        return move, boost, d, radius, to_center, to_next

    def choose_upgrade(self, offer, me):
        choices = (offer or {}).get("choices", [])
        if not choices:
            return None
        best_i, best_score = 0, -999
        for i, c in enumerate(choices):
            text = (str(c.get("id",""))+" "+str(c.get("name",""))+
                    " "+str(c.get("desc",""))).lower()
            score = 0
            if "armor" in text or "damage taken" in text: score += 15
            if "health" in text or "heal" in text or "regen" in text: score += 14
            if "damage" in text and "taken" not in text: score += 12
            if "gun" in text and ("rate" in text or "fire" in text): score += 10
            if "energy" in text: score += 8
            if "speed" in text or "mobility" in text: score += 8
            if "sensor" in text or "vision" in text: score += 5
            if score > best_score:
                best_i, best_score = i, score
        return best_i

    def act(self, obs):
        me = obs.get("self", {})
        pos = me.get("pos", [0,0,0])
        tick = obs.get("tick", 0)
        target = self.target(obs, me)

        move, boost, zone_d, zone_r, to_center, to_next = self.zone_move(obs, me)
        gun = get_weapon(me, 0)
        special = get_weapon(me, 1)

        aim = me.get("aim", [0,0])
        fire = [False, False]
        reload_gun = False
        take = None
        d = 9999

        # Fight visible enemies.
        if target:
            tp = target.get("pos", [0,0,0])
            d = dist(pos, tp)
            speed = max(1, (gun or {}).get("stats", {}).get(
                "speed", self.gun_cfg.get("speed", 252)))
            aim, _ = self.aim_at(me, target, min(1.0, d/speed))

            gun_range = (gun or {}).get("stats", {}).get(
                "range", self.gun_cfg.get("range", 230))
            if gun and d <= gun_range:
                if gun.get("ammo", 0) <= 0:
                    reload_gun = gun.get("reload", 0) <= 0
                else:
                    fire[0] = True

            if special:
                kind = special.get("kind")
                if kind == "laser":
                    charge = special.get("charge", 0)
                    charge_time = self.laser_cfg.get("charge", 0.75)
                    if d <= self.laser_cfg.get("range", 280):
                        # Charge first, release near maximum charge.
                        fire[1] = charge < charge_time*0.92
                        aim, _ = self.aim_at(me, target, min(0.3, d/500))
                elif kind == "lightning":
                    if d <= self.lightning_cfg.get("range", 45):
                        fire[1] = me.get("energy", 0) >= self.lightning_cfg.get("energy", 3)
                elif kind == "mortar":
                    if 55 < d <= self.mortar_cfg.get("range", 235):
                        v = self.mortar_cfg.get("speed", 72)
                        g = self.mortar_cfg.get("gravity", 22)
                        ratio = clamp(g*d/max(1,v*v), 0, 0.98)
                        aim, _ = self.aim_at(me, target, 0)
                        aim[1] = clamp(0.5*math.asin(ratio), -0.7, 1.25)
                        fire[1] = True

        # If no enemy, search toward recent sound.
        else:
            sounds = obs.get("sounds", [])
            recent = [s for s in sounds if s.get("age", 99) < 1.5
                      and s.get("dist") in ("near", "mid")]
            if recent:
                s = min(recent, key=lambda x:x.get("age",99))
                aim = [s.get("bearing", aim[0]), 0]
            else:
                aim = [((tick*0.12+int(me.get("id",0))*1.9)%(2*math.pi))-math.pi, 0]

        # Turn toward the last attacker if no close enemy.
        for ev in reversed(obs.get("events", [])):
            if ev.get("type") == "damaged" and ev.get("bearing") is not None:
                if not target or d > 45:
                    aim = [ev["bearing"], 0]
                break

        # Loot movement: cubes are the first choice when safely reachable.
        cube_target = None
        cubes = obs.get("cubes", [])
        if cubes:
            cube_target = min(cubes, key=lambda c: dist(pos, c.get("pos", pos)))
            cd = dist(pos, cube_target.get("pos", pos))
            if cd < 45 and zone_d < zone_r-70:
                cp = cube_target.get("pos", pos)
                toward = norm(cp[0]-pos[0], cp[1]-pos[1])
                move = norm(0.55*move[0]+0.45*toward[0],
                           0.55*move[1]+0.45*toward[1])
                if cd <= 3.5 and abs(cp[2]-pos[2]) <= 4:
                    # cubes are collected automatically; keep moving through them
                    move = toward

        # Weapon pickups only if slot 1 is empty.
        if special is None:
            pickups = [p for p in obs.get("pickups", [])
                       if p.get("kind") in ("laser","lightning","mortar")]
            if pickups:
                pick = min(pickups, key=lambda p: dist(pos,p.get("pos",pos)))
                pd = dist(pos, pick.get("pos",pos))
                pp = pick.get("pos", pos)
                if pd <= self.pickup_radius and abs(pp[2]-pos[2]) <= 4:
                    take = pick.get("id")
                elif pd < 30 and zone_d < zone_r-70 and (not target or d > 60):
                    toward = norm(pp[0]-pos[0], pp[1]-pos[1])
                    move = norm(0.65*move[0]+0.35*toward[0],
                               0.65*move[1]+0.35*toward[1])

        # Supply drop: approach only after it has landed and if no nearby enemy.
        drops = obs.get("drops", [])
        if drops and (not target or d > 75):
            available = [dr for dr in drops if dr.get("lands_in", 99) <= 0
                         and dr.get("holder") in (None, me.get("id"))]
            if available:
                dr = min(available, key=lambda x: dist(pos,x.get("pos",pos)))
                dp = dr.get("pos", pos)
                dd = dist(pos, dp)
                if dd < 65 and zone_d < zone_r-70:
                    toward = norm(dp[0]-pos[0], dp[1]-pos[1])
                    move = norm(0.45*move[0]+0.55*toward[0],
                               0.45*move[1]+0.55*toward[1])
                    if dd < 8:
                        move = [0,0]

        # Retreat from dangerously close enemy without leaving zone.
        if target and d < 30:
            away = norm(pos[0]-target["pos"][0], pos[1]-target["pos"][1])
            move = norm(0.7*away[0]+0.3*to_next[0],
                       0.7*away[1]+0.3*to_next[1])
            boost = me.get("energy",0) > 20

        # Jump if outside zone, grounded.
        jump = bool(me.get("grounded",False) and not me.get("in_zone",True)
                    and tick % 3 == 0)

        pick = self.choose_upgrade(obs.get("offer"), me)

        action = {"tick":tick, "move":move, "boost":bool(boost),
                  "jump":jump, "aim":aim, "fire":fire,
                  "reload":reload_gun}
        if take is not None:
            action["take"] = take
        if pick is not None:
            action["pick"] = pick
        return action

mf.run(Bot)
