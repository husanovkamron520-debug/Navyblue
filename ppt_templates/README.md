# Licensed PowerPoint design-reference library

Navyblue may fetch design references from [ai-ppt-template/free-ppt-template](https://github.com/ai-ppt-template/free-ppt-template).

- Catalog and template files are stated by that project to be licensed under **Creative Commons Attribution 4.0 International (CC BY 4.0)**.
- Each adapted reference must be credited: “Template design reference by ppttemplate.ai (CC BY 4.0); adapted for Navyblue.”
- License: https://creativecommons.org/licenses/by/4.0/
- Source: https://github.com/ai-ppt-template/free-ppt-template
- Downloaded decks are references only. Their original text, logos, photos and topic-specific claims must not be copied into generated decks.
- A catalog template is **not** assumed to contain Morph. The library inspects the actual PPTX package and marks Morph only when a slide transition contains a Morph element.
- The current renderer remains the owner of generated slide content and its own Morph transitions. Full slide cloning is intentionally not attempted with python-pptx because unsupported OOXML relationships/extensions may be lost.


At generation time, Navyblue selects one topic-matched reference, inspects it, and uses validated accent colors for automatic themes. If fetching or inspection fails, generation falls back to the built-in design system.
