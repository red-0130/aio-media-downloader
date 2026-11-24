import { describe, expect, it, mock } from 'bun:test';
import React from 'react';
import { renderToString } from 'react-dom/server';
import {
  UrlInput,
  PLATFORMS,
  canTriggerInspect,
  handleInspectSubmit,
  handleInputKeyDown,
  handlePillClick,
} from './UrlInput';

describe('UrlInput Component', () => {
  const defaultProps = {
    url: '',
    onChange: () => {},
    onInspect: () => {},
    isLoading: false,
    disabled: false,
  };

  describe('Desktop Layout & Sizing (Cut-off Prevention)', () => {
    it('renders input in size="fill" StackItem and buttons in size="static" StackItem', () => {
      const html = renderToString(
        React.createElement(UrlInput, {
          ...defaultProps,
          isMobile: false,
        })
      );

      // Verify StackItem structure
      expect(html).toContain('astryx-stack-item');
      expect(html).toContain('data-size="fill"');
      expect(html).toContain('data-size="static"');

      // Verify desktop placeholder
      expect(html).toContain(
        'placeholder="Paste video, reel, story, or post URL (YouTube, Instagram, Twitter/X, TikTok)..."'
      );

      // Verify action buttons exist in output
      expect(html).toContain('Paste');
      expect(html).toContain('Inspect Link');

      // Verify platform label and text are present on desktop
      expect(html).toContain('Supported platforms:');
      expect(html).toContain('YouTube');
      expect(html).toContain('Instagram');
      expect(html).toContain('Twitter / X');
      expect(html).toContain('TikTok');
    });
  });

  describe('Button States (Disabled vs Enabled)', () => {
    it('disables "Inspect Link" button when input URL is empty', () => {
      const html = renderToString(
        React.createElement(UrlInput, {
          ...defaultProps,
          url: '',
          isMobile: false,
        })
      );

      // Inspect Link button should be marked aria-disabled
      expect(html).toMatch(
        /<button[^>]*aria-disabled="true"[^>]*>[\s\S]*?Inspect Link[\s\S]*?<\/button>/
      );
    });

    it('disables "Inspect Link" button when input URL is only whitespace', () => {
      const html = renderToString(
        React.createElement(UrlInput, {
          ...defaultProps,
          url: '   ',
          isMobile: false,
        })
      );

      expect(html).toMatch(
        /<button[^>]*aria-disabled="true"[^>]*>[\s\S]*?Inspect Link[\s\S]*?<\/button>/
      );
    });

    it('enables "Inspect Link" button when input URL is non-empty', () => {
      const html = renderToString(
        React.createElement(UrlInput, {
          ...defaultProps,
          url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
          isMobile: false,
        })
      );

      // Should have Inspect Link button without aria-disabled="true"
      expect(html).toMatch(
        /<button(?!.*?aria-disabled="true")[^>]*>[\s\S]*?Inspect Link[\s\S]*?<\/button>/
      );
    });

    it('disables "Inspect Link" and displays loading state when isLoading is true', () => {
      const html = renderToString(
        React.createElement(UrlInput, {
          ...defaultProps,
          url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
          isLoading: true,
          isMobile: false,
        })
      );

      expect(html).toContain('Inspecting...');
      expect(html).toMatch(
        /<button[^>]*aria-disabled="true"[^>]*>[\s\S]*?Inspecting\.\.\.[\s\S]*?<\/button>/
      );
    });

    it('disables "Inspect Link" when disabled prop is true', () => {
      const html = renderToString(
        React.createElement(UrlInput, {
          ...defaultProps,
          url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
          disabled: true,
          isMobile: false,
        })
      );

      expect(html).toMatch(
        /<button[^>]*aria-disabled="true"[^>]*>[\s\S]*?Inspect Link[\s\S]*?<\/button>/
      );
    });
  });

  describe('Inspection Trigger Logic (Enter Key & Button Click Execution)', () => {
    it('evaluates canTriggerInspect correctly for boundary values', () => {
      expect(canTriggerInspect('', false)).toBe(false);
      expect(canTriggerInspect('   ', false)).toBe(false);
      expect(canTriggerInspect('https://x.com/post/1', false)).toBe(true);
      expect(canTriggerInspect('https://x.com/post/1', true)).toBe(false);
    });

    it('triggers onInspect via handleInspectSubmit when URL is valid and not loading', () => {
      const onInspect = mock(() => {});
      const handled = handleInspectSubmit(
        'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        false,
        onInspect
      );

      expect(handled).toBe(true);
      expect(onInspect).toHaveBeenCalledTimes(1);
    });

    it('does not trigger onInspect via handleInspectSubmit when URL is empty', () => {
      const onInspect = mock(() => {});
      const handled = handleInspectSubmit('', false, onInspect);

      expect(handled).toBe(false);
      expect(onInspect).toHaveBeenCalledTimes(0);
    });

    it('does not trigger onInspect via handleInspectSubmit when URL is only whitespace', () => {
      const onInspect = mock(() => {});
      const handled = handleInspectSubmit('    ', false, onInspect);

      expect(handled).toBe(false);
      expect(onInspect).toHaveBeenCalledTimes(0);
    });

    it('does not trigger onInspect via handleInspectSubmit during loading', () => {
      const onInspect = mock(() => {});
      const handled = handleInspectSubmit(
        'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        true,
        onInspect
      );

      expect(handled).toBe(false);
      expect(onInspect).toHaveBeenCalledTimes(0);
    });

    it('triggers onInspect and prevents default when Enter key is pressed with valid URL', () => {
      const onInspect = mock(() => {});
      let prevented = false;
      const event = {
        key: 'Enter',
        preventDefault: () => {
          prevented = true;
        },
      };

      const handled = handleInputKeyDown(
        event,
        'https://instagram.com/reel/12345',
        false,
        onInspect
      );

      expect(handled).toBe(true);
      expect(prevented).toBe(true);
      expect(onInspect).toHaveBeenCalledTimes(1);
    });

    it('does not trigger onInspect when Enter is pressed with empty URL', () => {
      const onInspect = mock(() => {});
      let prevented = false;
      const event = {
        key: 'Enter',
        preventDefault: () => {
          prevented = true;
        },
      };

      const handled = handleInputKeyDown(event, '', false, onInspect);

      expect(handled).toBe(false);
      expect(prevented).toBe(false);
      expect(onInspect).toHaveBeenCalledTimes(0);
    });

    it('does not trigger onInspect when Enter is pressed during loading', () => {
      const onInspect = mock(() => {});
      let prevented = false;
      const event = {
        key: 'Enter',
        preventDefault: () => {
          prevented = true;
        },
      };

      const handled = handleInputKeyDown(
        event,
        'https://tiktok.com/@test/video/1',
        true,
        onInspect
      );

      expect(handled).toBe(false);
      expect(prevented).toBe(false);
      expect(onInspect).toHaveBeenCalledTimes(0);
    });

    it('does not trigger onInspect on non-Enter key presses', () => {
      const onInspect = mock(() => {});
      let prevented = false;
      const event = {
        key: 'Tab',
        preventDefault: () => {
          prevented = true;
        },
      };

      const handled = handleInputKeyDown(
        event,
        'https://tiktok.com/@test/video/1',
        false,
        onInspect
      );

      expect(handled).toBe(false);
      expect(prevented).toBe(false);
      expect(onInspect).toHaveBeenCalledTimes(0);
    });
  });

  describe('Platform Preset Pills (Populate Input)', () => {
    it('defines preset configurations for all four primary platforms', () => {
      expect(PLATFORMS).toHaveLength(4);

      const names = PLATFORMS.map((p) => p.name);
      expect(names).toContain('YouTube');
      expect(names).toContain('Instagram');
      expect(names).toContain('Twitter / X');
      expect(names).toContain('TikTok');

      const yt = PLATFORMS.find((p) => p.name === 'YouTube');
      expect(yt?.domain).toBe('https://www.youtube.com/watch?v=');

      const ig = PLATFORMS.find((p) => p.name === 'Instagram');
      expect(ig?.domain).toBe('https://www.instagram.com/p/');

      const tw = PLATFORMS.find((p) => p.name === 'Twitter / X');
      expect(tw?.domain).toBe('https://x.com/user/status/');

      const tt = PLATFORMS.find((p) => p.name === 'TikTok');
      expect(tt?.domain).toBe('https://www.tiktok.com/@user/video/');
    });

    it('populates empty input when handlePillClick is called for each platform', () => {
      PLATFORMS.forEach((platform) => {
        const onChange = mock(() => {});
        const handled = handlePillClick(platform.domain, '', onChange);

        expect(handled).toBe(true);
        expect(onChange).toHaveBeenCalledTimes(1);
        expect(onChange).toHaveBeenCalledWith(platform.domain);
      });
    });

    it('populates whitespace-only input when handlePillClick is called', () => {
      const onChange = mock(() => {});
      const handled = handlePillClick(
        'https://www.youtube.com/watch?v=',
        '   ',
        onChange
      );

      expect(handled).toBe(true);
      expect(onChange).toHaveBeenCalledWith('https://www.youtube.com/watch?v=');
    });

    it('does not overwrite existing non-empty URL when handlePillClick is called', () => {
      const existingUrl = 'https://twitter.com/user/status/123';
      const onChange = mock(() => {});
      const handled = handlePillClick(
        'https://www.youtube.com/watch?v=',
        existingUrl,
        onChange
      );

      expect(handled).toBe(false);
      expect(onChange).toHaveBeenCalledTimes(0);
    });
  });

  describe('Mobile Layout & Icon-Only Platforms', () => {
    it('hides the "Supported platforms:" text label on mobile', () => {
      const html = renderToString(
        React.createElement(UrlInput, {
          ...defaultProps,
          isMobile: true,
        })
      );

      // Label must be completely absent in mobile view
      expect(html).not.toContain('Supported platforms:');
    });

    it('renders platform buttons in icon-only mode with aria-label and tooltips on mobile', () => {
      const html = renderToString(
        React.createElement(UrlInput, {
          ...defaultProps,
          isMobile: true,
        })
      );

      // Buttons rendered with isIconOnly have aria-label for accessibility
      expect(html).toContain('aria-label="YouTube"');
      expect(html).toContain('aria-label="Instagram"');
      expect(html).toContain('aria-label="Twitter / X"');
      expect(html).toContain('aria-label="TikTok"');

      // Astryx tooltip templates are attached
      expect(html).toContain('data-astryx-edge-comp=""');
    });

    it('uses stacked input and action rows on mobile', () => {
      const html = renderToString(
        React.createElement(UrlInput, {
          ...defaultProps,
          isMobile: true,
        })
      );

      // Mobile placeholder
      expect(html).toContain('placeholder="Paste video, reel, story, or post URL..."');

      // Paste button has static size StackItem, Inspect has fill size StackItem
      expect(html).toContain('data-size="static"');
      expect(html).toContain('data-size="fill"');
      expect(html).toContain('Paste');
      expect(html).toContain('Inspect Link');
    });
  });
});
