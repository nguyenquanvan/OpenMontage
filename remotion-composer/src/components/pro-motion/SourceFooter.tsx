import {interpolate, useCurrentFrame, useVideoConfig} from "remotion";
import type {SourceFooterProps} from "./types";

export const SourceFooter: React.FC<SourceFooterProps> = ({
  sourceLabel,
  textColor = "#17324D",
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  if (!sourceLabel) return null;

  return (
    <div
      style={{
        position: "absolute",
        left: 72,
        right: 72,
        bottom: 36,
        borderTop: `1px solid ${textColor}22`,
        paddingTop: 14,
        color: textColor,
        fontSize: 19,
        fontWeight: 600,
        letterSpacing: "0.01em",
        opacity: interpolate(frame, [0.7 * fps, 1.05 * fps], [0, 0.7], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        }),
      }}
    >
      NGUỒN · {sourceLabel}
    </div>
  );
};

