# SRD 5.1 — full text

The complete System Reference Document 5.1 as markdown, vendored so the
Rules Lawyer can **grep actual rule text instead of trusting model memory**.
Attribution and license: [Legal.md](Legal.md) (CC-BY-4.0).

Never load this wholesale into context — it's ~1,000 files. Grep for the
rule, read the one file that hits.

| Directory | What's in it |
|---|---|
| `01_Races/` | racial traits |
| `02_Classes/` | class features by level, one file per class |
| `03_Characterization/` | backgrounds, alignment, languages |
| `04_Equipment/` | weapons, armor, gear, mounts, treasure |
| `05_Feats/` | feats |
| `06_Gameplay/` | the core engine: abilities/checks, Adventuring (travel, rest, environment), Combat (actions, cover, grappling, mounted, underwater) |
| `07_Spells/` | `Spells_Each/` = one file per spell; `Spellcasting.md` = slots/concentration/ritual rules |
| `08_Gamemastering/` | conditions, diseases, madness, objects, poisons, traps |
| `09_Magic_Items/` | magic items A–Z, artifacts, sentient items |
| `10_Monsters/` | stat blocks A–Z, monster type lore |

Typical lookups:

```bash
grep -ril "grappl" rules/srd/06_Gameplay/
cat "rules/srd/07_Spells/Spells_Each/Counterspell.md"
grep -il "owlbear" rules/srd/10_Monsters/*.md
grep -n "Exhaustion" rules/srd/08_Gamemastering/Conditions.md
```
