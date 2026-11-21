import pyarrow as pa

from ..extract import Column, Extractor, Table


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

    def packet(self, p, f, world, emit):
        if (skill := f("skill_base[29]")) is not None:
            emit("evasion_skill", p, skill=skill & 0x7FFF)
