# Archived / hidden Navyblue features

The active Telegram reply keyboard is intentionally limited to **🚚 Logistika**.

The following non-logistics features are hidden from the visible menu, not deleted:
- Ta'lim roles and teacher/student menus
- SupplyChain14 classroom case tools and student/teacher workflows
- Slide / PowerPoint generation
- Referat, scientific article and thesis generation
- Tests, glossaries, case generation, crosswords and file-based study tools
- Feedback and statistics menu actions
- Museum module and its related routes/assets

Implementation note:
- Existing Python modules, handlers, data files and integrations are retained in the repository.
- The teacher/student menu builders now return the logistics-only menu.
- Pressing an old cached Ta'lim menu button no longer opens the education workflow.
- To restore a hidden feature later, re-enable its menu entry and its corresponding handler deliberately; do not delete archived code or stored data.

This is a visibility/workflow change, not a destructive cleanup.
