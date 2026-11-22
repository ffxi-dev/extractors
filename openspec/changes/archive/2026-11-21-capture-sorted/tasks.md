# Tasks

- [x] 1.1 entity_changes by capture first; setup sorts an existing table again. Verify `test_a_table_made_under_another_order_is_sorted_again_with_its_rows`, which fails on the old setup
- [x] 1.2 On prod, capture_entities and the capture page's parts read a capture's rows, not the table's, and a re-run of the archive goes faster: measured before and after. Measured 2026-11-22 on KDRkBynUt6A_: capture_entities 7.35M rows, 192 ms to 0.65M, 100 ms; the page's mobs part 103M, 4.0 s to 10.7M, 2.1 s; bestiary 32.7M, 1.3 s to 4.2M, 0.8 s. Re-running effects over the same 100 captures: 408 s to 245 s, ClickHouse no longer the bottleneck (the indexer now near 600% CPU, ClickHouse 190%)
