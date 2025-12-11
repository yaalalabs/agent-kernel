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
  const [showTooltip, setShowTooltip] = useState(true);
  const [hasInteracted, setHasInteracted] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Generate session ID on mount
  useEffect(() => {
    setSessionId(`session_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`);
  }, []);

  // Auto-hide tooltip after 10 seconds
  useEffect(() => {
    const timer = setTimeout(() => {
      setShowTooltip(false);
    }, 10000);
    return () => clearTimeout(timer);
  }, []);

  // Hide tooltip when chat opens for the first time (stays hidden)
  useEffect(() => {
    if (isOpen && !hasInteracted) {
      setShowTooltip(false);
      setHasInteracted(true);
    }
  }, [isOpen, hasInteracted]);

  // Auto scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Focus input when chat opens
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

    // Add typing indicator
    const typingId = `typing_${Date.now()}`;
    setMessages((prev) => [...prev, {
      id: typingId,
      text: '',
      sender: 'agent',
      timestamp: new Date(),
      isTyping: true,
    }]);

    try {
      const response = await fetch('https://4h9x2girbi.execute-api.ap-southeast-2.amazonaws.com/agents/api/v1/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          prompt: userMessage.text,
          session_id: sessionId,
          agent: 'general',
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();

      // Remove typing indicator
      setMessages((prev) => prev.filter((msg) => msg.id !== typingId));

      // Add agent response with typing animation
      const agentMessage: Message = {
        id: `agent_${Date.now()}`,
        text: data.result || 'Sorry, I couldn\'t process that request.',
        sender: 'agent',
        timestamp: new Date(),
        animated: false, // Will be animated
      };

      setMessages((prev) => [...prev, agentMessage]);
    } catch (error) {
      console.error('Error sending message:', error);

      // Remove typing indicator
      setMessages((prev) => prev.filter((msg) => msg.id !== typingId));

      const errorMessage: Message = {
        id: `error_${Date.now()}`,
        text: 'Sorry, I encountered an error. Please try again later.',
        sender: 'agent',
        timestamp: new Date(),
        animated: false, // Will be animated
      };

      setMessages((prev) => [...prev, errorMessage]);
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
    setIsOpen(!isOpen);
    if (isOpen) {
      setIsMaximized(false);
    }
  };

  const toggleMaximize = () => {
    setIsResizing(true);
    setIsMaximized(!isMaximized);

    // Reset resizing flag after transition completes (300ms transition in CSS)
    setTimeout(() => {
      setIsResizing(false);
    }, 350);
  };

  return (
    <>
      {/* Floating Chat Button */}
      {!isMaximized && (
        <div className={styles.chatButtonContainer}>
          {/* Tooltip */}
          {showTooltip && !isOpen && !hasInteracted && (
            <div className={styles.tooltip}>
              <div className={styles.tooltipContent}>
                <strong>💬 Ask AI Assistant</strong>
                <p>Get instant help with Agent Kernel documentation, examples, and more</p>
              </div>
              <div className={styles.tooltipArrow}></div>
            </div>
          )}

          {/* Chat Button */}
          <button
            className={`${styles.chatButton} ${isOpen ? styles.chatButtonOpen : ''}`}
            onClick={toggleChat}
            aria-label="Toggle AI Chat"
            onMouseEnter={() => setShowTooltip(true)}
          >
            {isOpen ? (
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            ) : (
              <>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="4" y="8" width="16" height="12" rx="2" />
                  <path d="M8 8V6a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  <circle cx="9" cy="14" r="1" fill="currentColor" />
                  <circle cx="15" cy="14" r="1" fill="currentColor" />
                  <path d="M9 17h6" />
                  <rect x="2" y="12" width="2" height="4" rx="1" />
                  <rect x="20" y="12" width="2" height="4" rx="1" />
                </svg>
              </>
            )}
            <span className={styles.pulseRing}></span>
            <span className={styles.pulseRing2}></span>
          </button>

          {/* Label Badge */}
          {!isOpen && !hasInteracted && (
            <div className={styles.chatLabel}>
              <span>AI Assistant</span>
            </div>
          )}
        </div>
      )}

      {/* Chat Window */}
      {isOpen && (
        <div className={`${styles.chatWindow} ${isMaximized ? styles.maximized : ''}`}>
          <div className={styles.chatHeader}>
            <div className={styles.headerLeft}>
              <div className={styles.agentAvatar}>
                <img src="/img/logo.svg" alt="Agent Kernel" className={styles.avatarLogo} />
              </div>
              <div>
                <h3 className={styles.chatTitle}>Agent Kernel AI</h3>
                <p className={styles.chatStatus}>
                  <span className={styles.statusDot}></span>
                  Online
                </p>
              </div>
            </div>
            <div className={styles.headerActions}>
              <button
                className={styles.resetButton}
                onClick={toggleMaximize}
                aria-label={isMaximized ? "Minimize chat" : "Maximize chat"}
                title={isMaximized ? "Minimize chat" : "Maximize chat"}
              >
                {isMaximized ? (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M8 3v3a2 2 0 0 1-2 2H3m18 0h-3a2 2 0 0 1-2-2V3m0 18v-3a2 2 0 0 1 2-2h3M3 16h3a2 2 0 0 1 2 2v3" />
                  </svg>
                ) : (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3m0 18h3a2 2 0 0 0 2-2v-3M3 16v3a2 2 0 0 0 2 2h3" />
                  </svg>
                )}
              </button>
              <button
                className={styles.resetButton}
                onClick={handleReset}
                aria-label="Reset conversation"
                title="Reset conversation"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
                  <path d="M21 3v5h-5" />
                  <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
                  <path d="M3 21v-5h5" />
                </svg>
              </button>
              {isMaximized && (
                <button
                  className={styles.resetButton}
                  onClick={toggleChat}
                  aria-label="Close chat"
                  title="Close chat"
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                </button>
              )}
            </div>
          </div>

          <div className={styles.chatMessages}>
            {messages.length === 0 && (
              <div className={styles.welcomeMessage}>
                <div className={styles.welcomeIcon}>
                  <img src="/img/logo.svg" alt="Agent Kernel" className={styles.welcomeLogo} />
                </div>
                <h4>Welcome to AI Assistant Powered by Agent Kernel</h4>
                <p>Ask me anything about Agent Kernel, AI agents, or how to get started!</p>
              </div>
            )}
            {messages.map((message) => (
              <MessageBubble
                key={message.id}
                message={message}
                isResizing={isResizing}
                onAnimationComplete={() => {
                  // Mark message as animated
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === message.id ? { ...m, animated: true } : m
                    )
                  );
                }}
              />
            ))}
            <div ref={messagesEndRef} />
          </div>

          <div className={styles.chatInputContainer}>
            <input
              ref={inputRef}
              type="text"
              className={styles.chatInput}
              placeholder="Ask me anything..."
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyPress={handleKeyPress}
              disabled={isLoading}
            />
            <button
              className={styles.sendButton}
              onClick={handleSendMessage}
              disabled={isLoading || !inputValue.trim()}
              aria-label="Send message"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
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

// Word wrapper component for fade-in animation
const AnimatedWord: React.FC<{ word: string; index: number }> = ({ word, index }) => {
  return (
    <span className={styles.animatedWord}>
      {word}
    </span>
  );
};

// Message Bubble Component with typing animation
const MessageBubble: React.FC<{ message: Message; onAnimationComplete?: () => void; isResizing: boolean }> = ({ message, onAnimationComplete, isResizing }) => {
  const [displayedText, setDisplayedText] = useState('');
  const [displayedWords, setDisplayedWords] = useState<string[]>([]);
  const [isAnimating, setIsAnimating] = useState(false);
  const messageRef = useRef<HTMLDivElement>(null);
  const animationRef = useRef<NodeJS.Timeout | null>(null);

  // Auto-scroll when displayed text changes during animation
  useEffect(() => {
    if (isAnimating && !isResizing && displayedText) {
      messageRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [displayedText, isAnimating, isResizing]);

  useEffect(() => {
    // If resizing, immediately complete the animation
    if (isResizing && isAnimating) {
      if (animationRef.current) {
        clearTimeout(animationRef.current);
        animationRef.current = null;
      }
      setDisplayedText(message.text);
      setIsAnimating(false);
      if (onAnimationComplete) {
        onAnimationComplete();
      }
      return;
    }
  }, [isResizing, isAnimating, message.text, onAnimationComplete]);

  useEffect(() => {
    // Clean up any existing animation timeout
    return () => {
      if (animationRef.current) {
        clearTimeout(animationRef.current);
        animationRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    // Only animate if it's an agent message, not typing, and hasn't been animated yet
    if (message.sender === 'agent' && !message.isTyping && !message.animated && !isResizing) {
      setIsAnimating(true);
      setDisplayedText('');
      setDisplayedWords([]);
      
      // Split text into words while preserving whitespace
      const words = message.text.split(/(\s+)/);
      let wordIndex = 0;

      const typeNextWord = () => {
        if (wordIndex < words.length) {
          // Build text progressively and update displayed words
          const textSoFar = words.slice(0, wordIndex + 1).join('');
          setDisplayedText(textSoFar);
          setDisplayedWords(words.slice(0, wordIndex + 1));
          wordIndex++;

          if (wordIndex < words.length) {
            // Adjust delay: shorter for whitespace, normal for words
            const currentWord = words[wordIndex - 1];
            const delay = currentWord.trim() === '' ? 0 : 100;
            animationRef.current = setTimeout(typeNextWord, delay);
          } else {
            setIsAnimating(false);
            animationRef.current = null;
            if (onAnimationComplete) {
              onAnimationComplete();
            }
          }
        }
      };

      // Start typing immediately
      typeNextWord();

      return () => {
        setIsAnimating(false);
        if (animationRef.current) {
          clearTimeout(animationRef.current);
          animationRef.current = null;
        }
      };
    } else {
      // Show full text immediately if already animated or is user message
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
            <span></span>
            <span></span>
            <span></span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div ref={messageRef} className={`${styles.messageWrapper} ${message.sender === 'user' ? styles.userMessage : styles.agentMessage}`}>
      <div className={styles.messageBubble}>
        {message.sender === 'agent' && !message.isTyping ? (
          <div className={styles.messageText}>
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeHighlight]}
              components={{
                // Custom component renderers for better styling
                code: ({ node, inline, className, children, ...props }: any) => {
                  return inline ? (
                    <code className={styles.inlineCode} {...props}>
                      {children}
                    </code>
                  ) : (
                    <code className={className} {...props}>
                      {children}
                    </code>
                  );
                },
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
                // Apply fade-in animation to text nodes during animation
                text: ({ node, children, ...props }: any) => {
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
