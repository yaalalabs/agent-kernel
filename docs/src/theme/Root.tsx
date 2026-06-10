import React from 'react';
import FloatingChatbot from '../components/FloatingChatbot';
import ScrollToTopButton from '../components/ScrollToTopButton/Scrolltotopbutton';

export default function Root({ children }) {
  return (
    <>
      {children}
      <ScrollToTopButton />
      <FloatingChatbot />
    </>
  );
}
