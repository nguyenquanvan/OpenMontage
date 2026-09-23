import {
  AbsoluteFill,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import {Fragment} from "react";
import {SourceFooter} from "./SourceFooter";
import type {MechanismNode} from "./types";

interface MechanismFlowProps {
  title?: string;
  subtitle?: string;
  nodes: MechanismNode[];
  sourceLabel?: string;
  backgroundColor?: string;
  textColor?: string;
  accentColor?: string;
  secondaryColor?: string;
}

export const MechanismFlow: React.FC<MechanismFlowProps> = ({
  title = "Cơ chế diễn ra như thế nào?",
  subtitle,
  nodes,
  sourceLabel,
  backgroundColor = "#F4EEDC",
  textColor = "#17324D",
  accentColor = "#D79A2B",
  secondaryColor = "#708B55",
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const visibleNodes = nodes.slice(0, 5);

  return (
    <AbsoluteFill style={{backgroundColor, color: textColor, padding: "72px 84px 92px"}}>
      <div
        style={{
          fontSize: 24,
          fontWeight: 800,
          letterSpacing: "0.18em",
          color: accentColor,
          opacity: interpolate(frame, [0, 10], [0, 1], {
            extrapolateRight: "clamp",
          }),
        }}
      >
        MECHANISM MAP
      </div>
      <div style={{fontSize: 58, lineHeight: 1.05, fontWeight: 850, marginTop: 18, maxWidth: 1320}}>
        {title}
      </div>
      {subtitle && (
        <div style={{fontSize: 28, lineHeight: 1.35, marginTop: 16, opacity: 0.68, maxWidth: 1160}}>
          {subtitle}
        </div>
      )}

      <div style={{display: "flex", alignItems: "center", marginTop: 86, width: "100%"}}>
        {visibleNodes.map((node, index) => {
          const delay = 12 + index * 11;
          const progress = spring({
            frame: frame - delay,
            fps,
            config: {damping: 18, stiffness: 105, mass: 0.8},
          });
          const connector = spring({
            frame: frame - delay - 7,
            fps,
            config: {damping: 22, stiffness: 90},
          });
          const activeColor = node.emphasis ? accentColor : secondaryColor;
          return (
            <Fragment key={`${node.label}-${index}`}>
              <div
                style={{
                  width: `${Math.max(170, 820 / visibleNodes.length)}px`,
                  minHeight: 238,
                  borderRadius: 28,
                  padding: "34px 28px",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  background: node.emphasis ? `${accentColor}18` : "rgba(255,255,255,0.72)",
                  border: `2px solid ${activeColor}`,
                  boxShadow: `0 20px 55px ${textColor}16`,
                  opacity: progress,
                  translate: `0 ${(1 - progress) * 42}px`,
                  scale: 0.9 + progress * 0.1,
                }}
              >
                <div
                  style={{
                    width: 46,
                    height: 46,
                    borderRadius: 999,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    backgroundColor: activeColor,
                    color: "#FFF9EA",
                    fontSize: 21,
                    fontWeight: 900,
                  }}
                >
                  {index + 1}
                </div>
                <div style={{fontSize: 31, lineHeight: 1.1, fontWeight: 850, marginTop: 20}}>{node.label}</div>
                {node.detail && <div style={{fontSize: 22, lineHeight: 1.35, opacity: 0.68, marginTop: 12}}>{node.detail}</div>}
              </div>
              {index < visibleNodes.length - 1 && (
                <div style={{flex: 1, minWidth: 72, height: 4, position: "relative", margin: "0 14px"}}>
                  <div style={{position: "absolute", inset: 0, backgroundColor: `${textColor}18`, borderRadius: 99}} />
                  <div
                    style={{
                      position: "absolute",
                      left: 0,
                      top: 0,
                      height: 4,
                      width: `${connector * 100}%`,
                      backgroundColor: accentColor,
                      borderRadius: 99,
                    }}
                  />
                  <div
                    style={{
                      position: "absolute",
                      right: -2,
                      top: -7,
                      width: 0,
                      height: 0,
                      borderTop: "9px solid transparent",
                      borderBottom: "9px solid transparent",
                      borderLeft: `14px solid ${accentColor}`,
                      opacity: connector,
                    }}
                  />
                </div>
              )}
            </Fragment>
          );
        })}
      </div>
      <SourceFooter sourceLabel={sourceLabel} textColor={textColor} />
    </AbsoluteFill>
  );
};
