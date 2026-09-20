# Photo Refiner Node Graph v1

The node branch adds a graph layer **above** the existing Photo Refiner v2.3 implementation. It does not replace the current image-processing scripts.

Default controlled flow:

```text
Source -> Look A -> Effect B? -> Approval -> Recovery? -> Delivery
```

The graph is intentionally semi-constrained rather than a free DAG. Users may enable, disable, configure, and later reposition supported nodes, but the execution order remains controlled.

## Look A semantics

The Look A node has two execution modes:

- `look-master`: render the normal Photo Refiner preset first. When Effect B follows, this corresponds to the existing `creative-from-base` behavior.
- `direction-only`: resolve A as an upstream visual direction without spending a separate image-generation pass. This preserves current v2.3 direct-effect behavior.

This distinction prevents the Canvas from silently adding a generation call.

## Effect B semantics

Effect B uses the bundled Starryear catalog and frozen `sourceCommit`.

- `direct-effect`: complete creative effect image, no original evidence assembly.
- `original-assembly`: original recipe layout/compositor behavior.

## Recovery semantics

- no B -> `normal`
- single-source direct-effect -> `creative-safe` unless detail is base-only
- original-assembly -> `disabled`
- multi-photo creative recipes -> `disabled` in graph v1

The current v2.3 pipeline remains the execution backend. The graph compiler produces an explicit plan instead of duplicating image-processing logic.
