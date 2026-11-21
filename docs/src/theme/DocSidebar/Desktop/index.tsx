import React from 'react';
import clsx from 'clsx';
import Link from '@docusaurus/Link';
import useBaseUrl from '@docusaurus/useBaseUrl';
import { useThemeConfig } from '@docusaurus/theme-common';
import ThemedImage from '@theme/ThemedImage';
import CollapseButton from '@theme/DocSidebar/Desktop/CollapseButton';
import Content from '@theme/DocSidebar/Desktop/Content';
import type { Props } from '@theme/DocSidebar/Desktop';
import styles from './styles.module.css';

/**
 * The stock docs sidebar, with one change: when the navbar hides on scroll the sidebar shows
 * the compact OAK lockup, not a copy of the navbar's full "Open Agent Kernel" lockup.
 */
function DocSidebarDesktop({ path, sidebar, onCollapse, isHidden }: Props): JSX.Element {
  const {
    navbar: { hideOnScroll },
    docs: {
      sidebar: { hideable },
    },
  } = useThemeConfig();
  const home = useBaseUrl('/');
  const sources = {
    light: useBaseUrl('/img/branding/oak-horizontal-color.svg'),
    dark: useBaseUrl('/img/branding/oak-horizontal-white-orange.svg'),
  };
  return (
    <div className={clsx(styles.sidebar, hideOnScroll && styles.sidebarWithHideableNavbar, isHidden && styles.sidebarHidden)}>
      {hideOnScroll && (
        <Link to={home} tabIndex={-1} className={styles.sidebarLogo} aria-label="Open Agent Kernel home">
          <ThemedImage sources={sources} alt="OAK" />
        </Link>
      )}
      <Content path={path} sidebar={sidebar} />
      {hideable && <CollapseButton onClick={onCollapse} />}
    </div>
  );
}

export default React.memo(DocSidebarDesktop);
