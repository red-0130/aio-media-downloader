import React from 'react';
import {
  TopNav,
  TopNavHeading,
  HStack,
  Button,
  Token,
  StatusDot,
  Text,
  useMediaQuery,
} from '@astryxdesign/core';
import { Download, Settings } from 'lucide-react';

export interface NavigationHeaderProps {
  onOpenSettings: () => void;
}

export const NavigationHeader: React.FC<NavigationHeaderProps> = ({ onOpenSettings }) => {
  const isMobile = useMediaQuery('(max-width: 640px)');

  return (
    <TopNav
      heading={
        <TopNavHeading
          logo={
            <Button
              variant="primary"
              size="sm"
              isIconOnly
              icon={<Download className="w-4 h-4 text-white" />}
              label="Cyber Media Studio Home"
            />
          }
          heading={isMobile ? 'Downloader' : 'All-in-One Downloader'}
          subheading={isMobile ? undefined : 'Universal Media Extraction Studio'}
        />
      }
      centerContent={
        !isMobile ? (
          <HStack gap={2} align="center">
            <Token size="sm" color="red" label="YouTube" />
            <Token size="sm" color="pink" label="Instagram" />
            <Token size="sm" color="cyan" label="Twitter/X" />
            <Token size="sm" color="teal" label="TikTok" />
          </HStack>
        ) : undefined
      }
      endContent={
        <HStack gap={2} align="center">
          <HStack gap={1} align="center">
            <StatusDot variant="success" isPulsing label="Engine Ready" />
            {!isMobile && (
              <Text type="supporting" color="secondary">
                Engine Ready
              </Text>
            )}
          </HStack>
          <Button
            variant="secondary"
            size="sm"
            icon={<Settings className="w-3.5 h-3.5 text-indigo-400" />}
            label="Settings"
            onClick={onOpenSettings}
          />
        </HStack>
      }
    />
  );
};

