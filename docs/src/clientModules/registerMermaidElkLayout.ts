/**
 * @docusaurus/theme-mermaid initializes mermaid but never registers extra layout
 * engines, so the `layout: 'elk'` option in docusaurus.config.js would silently
 * fall back to dagre without this. Registration must happen before the first
 * diagram renders; client modules load ahead of hydration, which guarantees that.
 */

import ExecutionEnvironment from '@docusaurus/ExecutionEnvironment';
import mermaid from 'mermaid';
import elkLayouts from '@mermaid-js/layout-elk';

if (ExecutionEnvironment.canUseDOM) {
  mermaid.registerLayoutLoaders(elkLayouts);
}
