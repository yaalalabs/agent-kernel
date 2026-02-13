import React from 'react';
import FloatingChatbot from '../components/FloatingChatbot';

export default function Root({ children }) {
  return (
    <>
      {children}
      <FloatingChatbot />
    </>
  );
}
