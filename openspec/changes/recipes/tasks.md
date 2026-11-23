# Tasks

- [x] 1.1 `synths` records the crafter's skill before each synthesis. Verify `tests/items/test_steal_dig_synth.py`, `rust/extractors/synths`
- [x] 1.2 `recipes` folds the character's syntheses by recipe and bounds its level. Verify `tests/facts/test_recipes.py`, `tests/test_expected.py`
- [x] 1.3 On the 34 archive captures with synthesis: every level step in `skills` follows a skill-up, and the bounds hold each level BG Wiki gives for the recipes checked
- [x] 1.4 On prod (2026-11-23, Scholar at extractors v2.2.0, scholar#313): synths v3 re-ran alone over 2,207 captures (1,985 jobs in 41 s, 222 passed by), recipes built once, pages 85 s. Every (table, capture) pair hashed before and after, every column but at and synths' new skills: 59,118 pairs, 69,435,940 rows, the same but synths on 5 live captures whose files had grown past their last full index. recipes: 269 rows over 33 captures, 233 recipes, 6,546 attempts; written twice at first by Scholar's plan for a new fact, put right by scholar#316
