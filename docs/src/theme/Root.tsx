import React from 'react';
import FloatingChatbot from '@site/src/components/FloatingChatbot';

// Root component wraps the entire app and persists across page navigation
export default function Root({ children }: { children: React.ReactNode }): JSX.Element {
  return (
    <>
      {children}
      <FloatingChatbot />
    </>
  );
}
