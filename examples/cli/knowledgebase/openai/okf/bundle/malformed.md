This file has no frontmatter block, so it is not a concept.

It is checked in on purpose: a bundle that contains one unreadable file must still load. The
file is skipped with an `unparseable_frontmatter` diagnostic, and `get_all_kb_descriptions`
reports the diagnostic to the agent rather than swallowing it.
