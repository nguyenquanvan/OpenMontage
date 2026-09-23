import {AbsoluteFill, Img, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {resolveAsset} from "../../lib/resolveAsset";
import {SourceFooter} from "./SourceFooter";

interface IngredientSpotlightProps {
  title: string;
  subtitle?: string;
  image?: string;
  badge?: string;
  facts?: string[];
  sourceLabel?: string;
  backgroundColor?: string;
  textColor?: string;
  accentColor?: string;
}

export const IngredientSpotlight: React.FC<IngredientSpotlightProps> = ({
  title,
  subtitle,
  image,
  badge = "INGREDIENT FOCUS",
  facts = [],
  sourceLabel,
  backgroundColor = "#F4EEDC",
  textColor = "#17324D",
  accentColor = "#D79A2B",
}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const heroProgress = spring({frame, fps, config: {damping: 18, stiffness: 80}});
  const drift = interpolate(frame, [0, durationInFrames], [-18, 18], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{backgroundColor, color: textColor, overflow: "hidden"}}>
      <div style={{position: "absolute", left: -120, top: -140, width: 720, height: 720, borderRadius: 999, backgroundColor: `${accentColor}16`, scale: 0.8 + heroProgress * 0.2}} />
      <div style={{display: "flex", width: "100%", height: "100%"}}>
        <div style={{width: "52%", padding: "92px 62px 100px 92px", display: "flex", flexDirection: "column", justifyContent: "center"}}>
          <div style={{fontSize: 22, letterSpacing: "0.18em", fontWeight: 900, color: accentColor}}>{badge}</div>
          <div style={{fontSize: 78, lineHeight: 0.98, fontWeight: 900, marginTop: 28, letterSpacing: "-0.045em", opacity: heroProgress, translate: `${(1 - heroProgress) * -60}px 0`}}>{title}</div>
          {subtitle && <div style={{fontSize: 29, lineHeight: 1.4, marginTop: 24, opacity: 0.67, maxWidth: 720}}>{subtitle}</div>}
          <div style={{display: "flex", flexDirection: "column", gap: 16, marginTop: 42}}>
            {facts.slice(0, 4).map((fact, index) => {
              const progress = spring({frame: frame - (16 + index * 8), fps, config: {damping: 20, stiffness: 95}});
              return (
                <div key={`${fact}-${index}`} style={{display: "flex", alignItems: "center", gap: 16, opacity: progress, translate: `${(1 - progress) * -34}px 0`}}>
                  <div style={{width: 13, height: 13, borderRadius: 99, backgroundColor: accentColor, flex: "0 0 auto"}} />
                  <div style={{fontSize: 25, lineHeight: 1.35, fontWeight: 650}}>{fact}</div>
                </div>
              );
            })}
          </div>
        </div>
        <div style={{width: "48%", padding: "68px 78px 82px 22px", position: "relative"}}>
          <div style={{position: "absolute", inset: "68px 78px 82px 22px", borderRadius: 38, overflow: "hidden", background: `linear-gradient(135deg, ${accentColor}2A, ${textColor}16)`, boxShadow: `0 35px 95px ${textColor}24`, opacity: heroProgress, translate: `0 ${(1 - heroProgress) * 55}px`, rotate: `${(1 - heroProgress) * 2.5}deg`}}>
            {image ? (
              <Img src={resolveAsset(image)} style={{width: "112%", height: "112%", objectFit: "cover", translate: `${-6 + drift * 0.16}% -6%`, scale: 1.05}} />
            ) : (
              <div style={{width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 160, background: `radial-gradient(circle, ${accentColor}30, transparent 66%)`}}>✦</div>
            )}
            <div style={{position: "absolute", inset: 0, background: "linear-gradient(180deg, transparent 55%, rgba(23,50,77,0.28))"}} />
          </div>
        </div>
      </div>
      <SourceFooter sourceLabel={sourceLabel} textColor={textColor} />
    </AbsoluteFill>
  );
};

