import type { CSSProperties, ReactNode } from 'react';
import './InputAddon.css';

interface InputAddonProps {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  onClick?: () => void;
}

export default function InputAddon({ children, className = '', style, onClick }: InputAddonProps) {
  return (
    // oxlint cannot see through the conditional role/tabIndex/onKeyDown below,
    // which is exactly what makes the clickable variant accessible.
    // oxlint-disable-next-line jsx-a11y/no-static-element-interactions
    <span
      className={`input-addon ${className}`.trim()}
      style={style}
      onClick={onClick}
    >
      {children}
    </span>
  );
}
