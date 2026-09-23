import {
  AbsoluteFill,
  Easing,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type {MotionIntensity} from "./types";

interface MotionFrameProps {
  children: React.ReactNode;
  transitionIn?: string;
  transitionOut?: string;
  transitionDuration?: number;
  intensity?: MotionIntensity;
  accentColor?: string;
}

const intensityScale: Record<MotionIntensity, number> = {
  subtle: 0.65,
  balanced: 1,
  dynamic: 1.35,
};

const clamp = {
  extrapolateLeft: "clamp" as const,
  extrapolateRight: "clamp" as const,
};

export const MotionFrame: React.FC<MotionFrameProps> = ({
  children,
  transitionIn = "fade",
  transitionOut = "fade",
  transitionDuration = 0.45,
  intensity = "balanced",
  accentColor = "#D79A2B",
}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const strength = intensityScale[intensity];
  const transitionFrames = Math.max(2, Math.round(transitionDuration * fps));
  const enter = interpolate(frame, [0, transitionFrames], [0, 1], {
    ...clamp,
    easing: Easing.bezier(0.16, 1, 0.3, 1),
  });
  const exit = interpolate(
    frame,
    [Math.max(0, durationInFrames - transitionFrames), durationInFrames],
    [1, 0],
    {...clamp, easing: Easing.bezier(0.7, 0, 0.84, 0)},
  );
  const inName = transitionIn.toLowerCase();
  const outName = transitionOut.toLowerCase();
  const hardIn = ["cut", "none", "hard-cut", "hard_cut"].includes(inName);
  const hardOut = ["cut", "none", "hard-cut", "hard_cut"].includes(outName);
  const entrance = hardIn ? 1 : enter;
  const departure = hardOut ? 1 : exit;

  let translateX = 0;
  let translateY = 0;
  let scale = 1;
  let clipPath: string | undefined;

  if (inName.includes("slide-left")) translateX = (1 - entrance) * 100 * strength;
  if (inName.includes("slide-right")) translateX = (1 - entrance) * -100 * strength;
  if (inName.includes("slide-up")) translateY = (1 - entrance) * 80 * strength;
  if (inName.includes("zoom")) scale = 1 + (1 - entrance) * 0.14 * strength;
  if (inName.includes("wipe")) clipPath = `inset(0 ${(1 - entrance) * 100}% 0 0 round 18px)`;
  if (inName.includes("iris")) clipPath = `circle(${entrance * 72}% at 50% 50%)`;

  if (outName.includes("slide-left")) translateX += (1 - departure) * -80 * strength;
  if (outName.includes("slide-right")) translateX += (1 - departure) * 80 * strength;
  if (outName.includes("slide-up")) translateY += (1 - departure) * -60 * strength;
  if (outName.includes("zoom")) scale += (1 - departure) * 0.1 * strength;
  if (outName.includes("wipe")) clipPath = `inset(0 0 0 ${(1 - departure) * 100}% round 18px)`;
  if (outName.includes("iris")) clipPath = `circle(${departure * 72}% at 50% 50%)`;

  const showSweep = inName.includes("light-sweep") || outName.includes("light-sweep");
  const sweepProgress = inName.includes("light-sweep")
    ? enter
    : 1 - exit;

  return (
    <AbsoluteFill style={{overflow: "hidden"}}>
      <AbsoluteFill
        style={{
          opacity: entrance * departure,
          translate: `${translateX}px ${translateY}px`,
          scale,
          clipPath,
        }}
      >
        {children}
      </AbsoluteFill>
      {showSweep && (
        <div
          style={{
            position: "absolute",
            top: "-25%",
            bottom: "-25%",
            width: 260,
            left: 0,
            translate: `${-360 + sweepProgress * 2460}px 0`,
            rotate: "12deg",
            background: `linear-gradient(90deg, transparent, ${accentColor}66, #FFFFFFAA, transparent)`,
            filter: "blur(12px)",
            mixBlendMode: "screen",
            opacity: intensity === "subtle" ? 0.45 : 0.75,
          }}
        />
      )}
    </AbsoluteFill>
  );
};

