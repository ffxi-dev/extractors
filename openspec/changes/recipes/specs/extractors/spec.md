# Spec Delta

## ADDED Requirements

### Requirement: A synthesis records the crafter's skill before it
The synths extractor SHALL record, for each of the character's own syntheses, its level in each craft the result names (UpKind): one under the level a skill-up message (0x029, message 53) reached since the last synthesis, else the level the last skills update (0x062) gave, bits 5 to 14 of `skill_base`.

#### Scenario: A skill-up that reaches a level
- **WHEN** smithing is 12, message 53 says smithing reached 13, a 0x062 shows 13, and then the result comes
- **THEN** that synthesis's smithing skill is 12, and the next one's is 13

### Requirement: A recipe's level is bounded by its skill-ups
The recipes fact SHALL fold the character's syntheses by crystal and ingredients, and for each craft SHALL bound the recipe's level from the skill-ups at skill S: at least S - 10 for one on a success, from S + 1 to S + 5 for one on a break, and at most S + 27 for any attempt.

#### Scenario: A skill-up on a break
- **WHEN** smithing rises on a break at skill 12 and on a success at skill 20
- **THEN** the recipe's smithing level is from 13 to 17
