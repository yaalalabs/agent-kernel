import React, { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import 'highlight.js/styles/github-dark.css';
import styles from './styles.module.css';

interface Message {
  id: string;
  text: string;
  sender: 'user' | 'agent';
  timestamp: Date;
  isTyping?: boolean;
  animated?: boolean;
}

const FloatingChatbot: React.FC = () => {
  const [isOpen, setIsOpen] = useState(false);
  const [isMaximized, setIsMaximized] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState('');
  const [isResizing, setIsResizing] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setSessionId(`session_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`);
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (isOpen) {
      inputRef.current?.focus();
    }
  }, [isOpen]);

  const handleSendMessage = async () => {
    if (!inputValue.trim() || isLoading) return;

    const userMessage: Message = {
      id: `user_${Date.now()}`,
      text: inputValue,
      sender: 'user',
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInputValue('');
    setIsLoading(true);

    const typingId = `typing_${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      { id: typingId, text: '', sender: 'agent', timestamp: new Date(), isTyping: true },
    ]);

    try {
      const response = await fetch(
        'https://63e0emv8qf.execute-api.ap-southeast-1.amazonaws.com/agents/api/v1/chat',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt: userMessage.text,
            session_id: sessionId,
            agent: 'general',
          }),
        }
      );

      if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

      const data = await response.json();
      setMessages((prev) => prev.filter((msg) => msg.id !== typingId));
      setMessages((prev) => [
        ...prev,
        {
          id: `agent_${Date.now()}`,
          text: data.result || "Sorry, I couldn't process that request.",
          sender: 'agent',
          timestamp: new Date(),
          animated: false,
        },
      ]);
    } catch (error) {
      console.error('Error sending message:', error);
      setMessages((prev) => prev.filter((msg) => msg.id !== typingId));
      setMessages((prev) => [
        ...prev,
        {
          id: `error_${Date.now()}`,
          text: 'Sorry, I encountered an error. Please try again later.',
          sender: 'agent',
          timestamp: new Date(),
          animated: false,
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const handleReset = () => {
    setMessages([]);
    setSessionId(`session_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`);
  };

  const toggleChat = () => {
    setIsOpen((prev) => !prev);
    if (isOpen) setIsMaximized(false);
  };

  const toggleMaximize = () => {
    setIsResizing(true);
    setIsMaximized((prev) => !prev);
    setTimeout(() => setIsResizing(false), 350);
  };

  return (
    <>
      {/* Trigger Button */}
      {!isMaximized && (
        <div className={styles.chatButtonContainer}>
          <button
            className={`${styles.chatButton} ${isOpen ? styles.chatButtonOpen : ''}`}
            onClick={toggleChat}
            aria-label={isOpen ? 'Close chat' : 'Open Agent Kernel AI'}
          >
            {isOpen ? (
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
              >
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            ) : (
              <img
                src="/img/branding/agent-kernel-icon-mono-white.svg"
                alt="Agent Kernel"
                className={styles.buttonLogo}
              />
            )}
            {!isOpen && <span className={styles.pulseRing} />}
          </button>
        </div>
      )}

      {/* Chat Window */}
      {isOpen && (
        <div className={`${styles.chatWindow} ${isMaximized ? styles.maximized : ''}`}>
          {/* Header */}
          <div className={styles.chatHeader}>
            <div className={styles.headerLeft}>
              <div className={styles.agentAvatar}>
                <img
                  src="/img/branding/agent-kernel-icon-color.svg"
                  alt="Agent Kernel"
                  className={styles.avatarLogo}
                />
              </div>
              <div>
                <h3 className={styles.chatTitle}>Agent Kernel</h3>
                <p className={styles.chatStatus}>
                  <span className={styles.statusDot} />
                  Online
                </p>
              </div>
            </div>
            <div className={styles.headerActions}>
              <button
                className={styles.iconButton}
                onClick={toggleMaximize}
                aria-label={isMaximized ? 'Minimize chat' : 'Expand chat'}
                title={isMaximized ? 'Minimize' : 'Expand'}
              >
                {isMaximized ? (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3" />
                  </svg>
                ) : (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
                  </svg>
                )}
              </button>
              <button
                className={styles.iconButton}
                onClick={handleReset}
                aria-label="New conversation"
                title="New conversation"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
                  <path d="M21 3v5h-5" />
                  <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
                  <path d="M3 21v-5h5" />
                </svg>
              </button>
              {isMaximized && (
                <button
                  className={styles.iconButton}
                  onClick={toggleChat}
                  aria-label="Close chat"
                  title="Close"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                </button>
              )}
            </div>
          </div>

          {/* Messages */}
          <div className={styles.chatMessages}>
            {messages.length === 0 && (
              <div className={styles.welcomeMessage}>
                <div className={styles.welcomeIcon}>
                  <img
                    src="/img/branding/agent-kernel-icon-color.svg"
                    alt="Agent Kernel"
                    className={styles.welcomeLogo}
                  />
                </div>
                <h4>How can I help?</h4>
                <p>Ask me anything about Agent Kernel — setup, agents, integrations, and more.</p>
              </div>
            )}
            {messages.map((message) => (
              <MessageBubble
                key={message.id}
                message={message}
                isResizing={isResizing}
                onAnimationComplete={() => {
                  setMessages((prev) =>
                    prev.map((m) => (m.id === message.id ? { ...m, animated: true } : m))
                  );
                }}
              />
            ))}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className={styles.chatInputContainer}>
            <input
              ref={inputRef}
              type="text"
              className={styles.chatInput}
              placeholder="Ask anything..."
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyPress}
              disabled={isLoading}
            />
            <button
              className={styles.sendButton}
              onClick={handleSendMessage}
              disabled={isLoading || !inputValue.trim()}
              aria-label="Send message"
            >
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            </button>
          </div>
        </div>
      )}
    </>
  );
};

// Word wrapper for animated text
const AnimatedWord: React.FC<{ word: string; index: number }> = ({ word }) => {
  return <span className={styles.animatedWord}>{word}</span>;
};

// Message bubble with word-by-word typing animation
const MessageBubble: React.FC<{
  message: Message;
  onAnimationComplete?: () => void;
  isResizing: boolean;
}> = ({ message, onAnimationComplete, isResizing }) => {
  const [displayedText, setDisplayedText] = useState('');
  const [displayedWords, setDisplayedWords] = useState<string[]>([]);
  const [isAnimating, setIsAnimating] = useState(false);
  const messageRef = useRef<HTMLDivElement>(null);
  const animationRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    if (isAnimating && !isResizing && displayedText) {
      messageRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [displayedText, isAnimating, isResizing]);

  useEffect(() => {
    if (isResizing && isAnimating) {
      if (animationRef.current) {
        clearTimeout(animationRef.current);
        animationRef.current = null;
      }
      setDisplayedText(message.text);
      setIsAnimating(false);
      if (onAnimationComplete) onAnimationComplete();
    }
  }, [isResizing, isAnimating, message.text, onAnimationComplete]);

  useEffect(() => {
    return () => {
      if (animationRef.current) {
        clearTimeout(animationRef.current);
        animationRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (message.sender === 'agent' && !message.isTyping && !message.animated && !isResizing) {
      setIsAnimating(true);
      setDisplayedText('');
      setDisplayedWords([]);

      const words = message.text.split(/(\s+)/);
      let wordIndex = 0;

      const typeNextWord = () => {
        if (wordIndex < words.length) {
          const textSoFar = words.slice(0, wordIndex + 1).join('');
          setDisplayedText(textSoFar);
          setDisplayedWords(words.slice(0, wordIndex + 1));
          wordIndex++;

          if (wordIndex < words.length) {
            const currentWord = words[wordIndex - 1];
            const delay = currentWord.trim() === '' ? 0 : 100;
            animationRef.current = setTimeout(typeNextWord, delay);
          } else {
            setIsAnimating(false);
            animationRef.current = null;
            if (onAnimationComplete) onAnimationComplete();
          }
        }
      };

      typeNextWord();

      return () => {
        setIsAnimating(false);
        if (animationRef.current) {
          clearTimeout(animationRef.current);
          animationRef.current = null;
        }
      };
    } else {
      setDisplayedText(message.text);
      setDisplayedWords([]);
      setIsAnimating(false);
    }
  }, [message, onAnimationComplete, isResizing]);

  if (message.isTyping) {
    return (
      <div className={`${styles.messageWrapper} ${styles.agentMessage}`}>
        <div className={styles.messageBubble}>
          <div className={styles.typingIndicator}>
            <span />
            <span />
            <span />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={messageRef}
      className={`${styles.messageWrapper} ${
        message.sender === 'user' ? styles.userMessage : styles.agentMessage
      }`}
    >
      <div className={styles.messageBubble}>
        {message.sender === 'agent' && !message.isTyping ? (
          <div className={styles.messageText}>
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeHighlight]}
              components={{
                code: ({ node, inline, className, children, ...props }: any) =>
                  inline ? (
                    <code className={styles.inlineCode} {...props}>
                      {children}
                    </code>
                  ) : (
                    <code className={className} {...props}>
                      {children}
                    </code>
                  ),
                a: ({ node, children, ...props }: any) => (
                  <a {...props} target="_blank" rel="noopener noreferrer" className={styles.messageLink}>
                    {children}
                  </a>
                ),
                p: ({ node, children, ...props }: any) => (
                  <p className={styles.messageParagraph} {...props}>
                    {children}
                  </p>
                ),
                ul: ({ node, children, ...props }: any) => (
                  <ul className={styles.messageList} {...props}>
                    {children}
                  </ul>
                ),
                ol: ({ node, children, ...props }: any) => (
                  <ol className={styles.messageList} {...props}>
                    {children}
                  </ol>
                ),
                text: ({ children }: any) => {
                  if (isAnimating && displayedWords.length > 0) {
                    const text = String(children);
                    const words = text.split(/(\s+)/);
                    return (
                      <>
                        {words.map((word, index) => (
                          <AnimatedWord key={index} word={word} index={index} />
                        ))}
                      </>
                    );
                  }
                  return <>{children}</>;
                },
              }}
            >
              {displayedText}
            </ReactMarkdown>
            {isAnimating && <span className={styles.cursor}>|</span>}
          </div>
        ) : (
          <p className={styles.messageText}>{displayedText}</p>
        )}
      </div>
      <span className={styles.messageTime}>
        {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
      </span>
    </div>
  );
};

export default FloatingChatbot;
