import {AbsoluteFill, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {SourceFooter} from "./SourceFooter";
import type {TimelineStep} from "./types";

interface TimelineStepsProps {
  title?: string;
  subtitle?: string;
  steps: TimelineStep[];
  sourceLabel?: string;
  backgroundColor?: string;
  textColor?: string;
  accentColor?: string;
  secondaryColor?: string;
}

export const TimelineSteps: React.FC<TimelineStepsProps> = ({
  title = "Điều gì xảy ra theo thời gian?",
  subtitle,
  steps,
  sourceLabel,
  backgroundColor = "#F4EEDC",
  textColor = "#17324D",
  accentColor = "#D79A2B",
  secondaryColor = "#708B55",
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const items = steps.slice(0, 6);
  const lineProgress = spring({frame: frame - 8, fps, config: {damping: 24, stiffness: 70}});

  return (
    <AbsoluteFill style={{backgroundColor, color: textColor, padding: "72px 86px 92px"}}>
      <div style={{fontSize: 23, letterSpacing: "0.18em", color: accentColor, fontWeight: 850}}>ANIMATED TIMELINE</div>
      <div style={{fontSize: 58, lineHeight: 1.05, fontWeight: 850, marginTop: 18}}>{title}</div>
      {subtitle && <div style={{fontSize: 27, opacity: 0.68, marginTop: 16}}>{subtitle}</div>}
      <div style={{position: "relative", flex: 1, display: "flex", alignItems: "center", marginTop: 24}}>
        <div style={{position: "absolute", left: 80, right: 80, top: "48%", height: 7, backgroundColor: `${textColor}16`, borderRadius: 99}} />
        <div style={{position: "absolute", left: 80, top: "48%", height: 7, width: `calc((100% - 160px) * ${lineProgress})`, background: `linear-gradient(90deg, ${secondaryColor}, ${accentColor})`, borderRadius: 99}} />
        <div style={{display: "flex", justifyContent: "space-between", width: "100%", gap: 24, padding: "0 44px"}}>
          {items.map((step, index) => {
            const progress = spring({frame: frame - (15 + index * 9), fps, config: {damping: 16, stiffness: 105}});
            const top = index % 2 === 0;
            return (
              <div key={`${step.label}-${index}`} style={{width: `${92 / items.length}%`, minWidth: 170, height: 520, position: "relative", opacity: progress}}>
                <div
                  style={{
                    position: "absolute",
                    left: "50%",
                    top: "48%",
                    width: 34,
                    height: 34,
                    borderRadius: 999,
                    backgroundColor: index === items.length - 1 ? accentColor : secondaryColor,
                    border: `7px solid ${backgroundColor}`,
                    boxShadow: `0 0 0 2px ${index === items.length - 1 ? accentColor : secondaryColor}`,
                    translate: "-50% -13px",
                    scale: progress,
                  }}
                />
                <div
                  style={{
                    position: "absolute",
                    left: "50%",
                    top: top ? 28 : "55%",
                    translate: `${(1 - progress) * (top ? -24 : 24)}px 0`,
                    width: 245,
                    marginLeft: -122,
                    textAlign: "center",
                  }}
                >
                  {step.time && <div style={{fontSize: 17, fontWeight: 900, color: accentColor, letterSpacing: "0.08em"}}>{step.time}</div>}
                  <div style={{fontSize: 27, fontWeight: 850, lineHeight: 1.15, marginTop: 10}}>{step.label}</div>
                  {step.detail && <div style={{fontSize: 19, lineHeight: 1.35, opacity: 0.64, marginTop: 10}}>{step.detail}</div>}
                </div>
              </div>
            );
          })}
        </div>
      </div>
      <SourceFooter sourceLabel={sourceLabel} textColor={textColor} />
    </AbsoluteFill>
  );
};

