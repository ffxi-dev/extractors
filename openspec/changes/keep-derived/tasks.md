# Tasks

- [x] 1.1 `store.pending` and `setup(keep=True)`. Verify `test_setup_keeping_a_changed_derived_table_leaves_its_rows_and_lists_it` (#101)
- [x] 1.1a A fact over a kept table is kept too, unread, and the views wait for the rebuild. Verify `test_setup_keeping_a_table_a_later_fact_cannot_read_yet_leaves_both` (#104)
- [ ] 1.2 Scholar sets up with `keep=True` and rebuilds what `pending` lists (scholar, vault `release-schema` 1.2)
- [ ] 2.1 `store.sorts` and `copy_sorted`; `setup(keep=True)` leaves a capture-row table sorted otherwise for the caller. Verify `test_setup_keeping_a_table_sorted_otherwise_leaves_it_for_the_caller`
- [ ] 2.2 Scholar re-sorts what `sorts` lists in its rebuild journal (vault `release-schema` 2.2)
