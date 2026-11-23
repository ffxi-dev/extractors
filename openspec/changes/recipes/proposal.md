# Proposal

## Why

The owner wants a recipe book from the captures: each recipe's crystal and ingredients, what each grade made, how often each came, and the recipe's craft level as far as skill-ups show it. `synths` holds the character's own results with crystal, ingredients, grade, and skill-ups (UpKind, UpLevel), but not the crafter's skill.

## What Changes

- `synths` v3 reads the character's skills (0x062) and skill-up messages (0x029) and records `skills`: the level in each craft of `skill_kinds` before the synthesis. Retail sends a skill-up's message 53 ("reaches level N") and the 0x062 that shows it before the result (0x06F) of the synthesis that raised it, so after a message 53 the level before is N - 1.
- New derived fact `recipes`: one row per capture, crystal, and ingredients (item id and quantity, sorted), with attempts, NQ, HQ1 to HQ3 and break counts, each grade's item and count, and per craft the skill-ups and the bounds they put on the recipe's level.
- The bounds follow FFO Wiki's 合成 (since 2015-05-14): a skill-up on a success at skill S gives level >= S - 10, on a break S + 1 <= level <= S + 5; any attempt gives level <= S + 27. An attempt with no skill-up bounds nothing.

## Impact

- `extractors/items/synths.py`, `rust/extractors/synths`, `rust/xc-all`; `facts/recipes.py`, `facts/__init__.py`; pins `synths-v3.json`, `recipes-v1.json`.
- `synths` now reads 0x062 and 0x029, which nearly every capture holds: Scholar re-runs it over the archive once.
