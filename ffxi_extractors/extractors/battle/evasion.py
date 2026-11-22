import pyarrow as pa

from ffxi_extractors.extract import Column, Extractor, Table


class EvasionSkill(Extractor):
    name = "evasion_skill"
    version = 1
    doc = "The recording character's evasion skill, from its skills (0x062)."
    reads = frozenset({(0, 0x062)})
    tables = (
        Table(
            "evasion_skill",
            "One row per skills update (0x062) that gives the recorder's evasion skill (skill_base[29]). The"
            " bestiary's evasion floor reads it when no /checkparam reply gives evasion.",
            (Column("skill", pa.int32(), "Evasion skill, the rank bit masked off."),),
        ),
    )
