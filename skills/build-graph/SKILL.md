---
name: build-graph
description: Build a knowledge graph from the current workspace using graphify, then embed all nodes for semantic search. Use when the user wants to analyze codebase structure.
---

# Build Knowledge Graph

1. Run `/graphify` on the current directory to build the knowledge graph
2. After the graph is built, embed all nodes for semantic search:
```bash
python -c "
import sys; sys.path.insert(0, '${CLAUDE_PLUGIN_ROOT}')
from tentaqles.embeddings.graphify_hook import embed_graph
result = embed_graph('graphify-out/graph.json')
print(f'Embedded {result[\"nodes_embedded\"]} nodes ({result[\"file_size_kb\"]} KB)')
"
```
3. Tell the user they can now use `/tentaqles:query-memory` for semantic search
