import {AbsoluteFill, Img, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {loadFont} from "@remotion/google-fonts/PatrickHand";
import {resolveAsset} from "../lib/resolveAsset";

// Loaded at module level so every scene of a chalkboard theme (whose
// headingFont is "Patrick Hand") renders in it, Vietnamese diacritics included.
const {fontFamily: chalkFont} = loadFont("normal", {
  weights: ["400"],
  subsets: ["latin", "latin-ext", "vietnamese"],
});

export interface ChalkSceneProps {
  /** Chalk drawing on a dark board. Omit for a sentence-only chalk card. */
  image?: string;
  /** Sentence written across the top. Omit when the image already carries its text. */
  text?: string;
  /** Single words of `text` drawn in the accent chalk and underlined. */
  highlightWords?: string[];
  /** Large chalk numeral beside the drawing, e.g. a countdown "5". */
  badge?: string;
  sourceLabel?: string;
  /** zoom-in (default) | zoom-out | pan-left | pan-right | static */
  animation?: string;
  boardColor?: string;
  chalkColor?: string;
  accentColor?: string;
}

const WORD_FADE_SECONDS = 0.18;

const normalizeWord = (word: string): string =>
  word.replace(/[^\p{L}\p{N}%]/gu, "").toLowerCase();

export const ChalkScene: React.FC<ChalkSceneProps> = ({
  image,
  text,
  highlightWords = [],
  badge,
  sourceLabel,
  animation = "zoom-in",
  boardColor = "#23272A",
  chalkColor = "#F4F1E8",
  accentColor = "#F2D16B",
}) => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames, width, height} = useVideoConfig();
  const portrait = height > width;
  const scale = portrait ? width / 1080 : width / 1920;

  // NFC keeps Vietnamese letters as single code points inside each word span.
  const words = (text ?? "").normalize("NFC").split(/\s+/).filter(Boolean);
  const hasText = words.length > 0;
  const highlights = new Set(highlightWords.map(normalizeWord).filter(Boolean));
  const writeSeconds = Math.min(2.2, Math.max(0.6, words.length * 0.12));

  const baseSize = (portrait ? 58 : 66) * scale;
  const longText = words.join(" ").length > 80;
  const fontSize = hasText && !image ? baseSize * 1.35 : longText ? baseSize * 0.85 : baseSize;

  const progress = interpolate(frame, [0, durationInFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  let imageScale = 1;
  let imageShiftX = 0;
  if (animation === "zoom-in") imageScale = 1 + progress * 0.06;
  else if (animation === "zoom-out") imageScale = 1.06 - progress * 0.06;
  else if (animation === "pan-left") {
    imageScale = 1.05;
    imageShiftX = interpolate(progress, [0, 1], [2, -2]);
  } else if (animation === "pan-right") {
    imageScale = 1.05;
    imageShiftX = interpolate(progress, [0, 1], [-2, 2]);
  }

  // The sentence leads; the drawing fades up under it.
  const imageStart = hasText ? Math.min(writeSeconds * 0.5, 0.6) * fps : 0;
  const imageOpacity = interpolate(frame, [imageStart, imageStart + 0.5 * fps], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const badgeIn = spring({frame: frame - imageStart, fps, config: {damping: 16, stiffness: 90}});

  const chalkText = {
    fontFamily: chalkFont,
    color: chalkColor,
    textShadow: `0 0 ${1.2 * scale}px ${chalkColor}, 0 0 ${9 * scale}px rgba(255,255,255,0.12)`,
  };

  const sentence = hasText ? (
    <div
      style={{
        ...chalkText,
        fontSize,
        lineHeight: 1.18,
        textAlign: "center",
        maxWidth: "88%",
        margin: "0 auto",
      }}
    >
      {words.map((word, index) => {
        const start = (index / words.length) * writeSeconds * fps;
        const opacity = interpolate(frame, [start, start + WORD_FADE_SECONDS * fps], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        });
        const highlighted = highlights.has(normalizeWord(word));
        // Punctuation stays outside the underline: "yogurt," underlines "yogurt".
        const [, lead, core, trail] = highlighted
          ? word.match(/^([^\p{L}\p{N}%]*)(.*?)([^\p{L}\p{N}%]*)$/u) ?? ["", "", word, ""]
          : ["", "", word, ""];
        return (
          <span
            key={`${word}-${index}`}
            style={{
              opacity,
              display: "inline-block",
              marginRight: "0.28em",
              translate: `0 ${(1 - opacity) * 6 * scale}px`,
            }}
          >
            {lead}
            <span
              style={
                highlighted
                  ? {
                      color: accentColor,
                      textDecoration: "underline",
                      textDecorationColor: accentColor,
                      textDecorationThickness: Math.max(2, 3 * scale),
                      textUnderlineOffset: 10 * scale,
                    }
                  : undefined
              }
            >
              {core}
            </span>
            {trail}
          </span>
        );
      })}
    </div>
  ) : null;

  const board = (
    <AbsoluteFill
      style={{
        backgroundColor: boardColor,
        backgroundImage:
          "radial-gradient(ellipse at 28% 22%, rgba(255,255,255,0.07), transparent 58%)," +
          "radial-gradient(ellipse at 76% 78%, rgba(255,255,255,0.05), transparent 55%)," +
          "radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,0.45) 100%)",
      }}
    />
  );

  const footer = sourceLabel ? (
    <div
      style={{
        ...chalkText,
        position: "absolute",
        right: 48 * scale,
        bottom: 28 * scale,
        fontSize: 22 * scale,
        opacity: 0.65,
      }}
    >
      {sourceLabel}
    </div>
  ) : null;

  // The image already carries its sentence: show it full-frame.
  if (image && !hasText) {
    return (
      <AbsoluteFill style={{overflow: "hidden"}}>
        {board}
        <Img
          src={resolveAsset(image)}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            opacity: imageOpacity,
            transform: `scale(${imageScale}) translateX(${imageShiftX}%)`,
          }}
        />
        {footer}
      </AbsoluteFill>
    );
  }

  // Sentence-only chalk card.
  if (!image) {
    return (
      <AbsoluteFill style={{overflow: "hidden", justifyContent: "center"}}>
        {board}
        <div style={{position: "relative", padding: "0 6%"}}>{sentence}</div>
        {footer}
      </AbsoluteFill>
    );
  }

  // Sentence on top, drawing below. The frame hugs the drawing (16:9), and its
  // feathered edges plus the lighten blend melt the drawing's own board into
  // ours so no rectangle edge shows.
  const featherX = "linear-gradient(to right, transparent, #000 9%, #000 91%, transparent)";
  const featherY = "linear-gradient(to bottom, transparent, #000 9%, #000 91%, transparent)";
  return (
    <AbsoluteFill style={{overflow: "hidden"}}>
      {board}
      <AbsoluteFill
        style={{
          flexDirection: "column",
          padding: portrait
            ? `${height * 0.07}px ${width * 0.05}px ${height * 0.08}px`
            : `${height * 0.045}px ${width * 0.06}px ${height * 0.04}px`,
        }}
      >
        {sentence}
        <div style={{position: "relative", flex: 1, marginTop: 18 * scale}}>
          <div
            style={{
              position: "absolute",
              top: 0,
              bottom: 0,
              left: "50%",
              translate: "-50% 0",
              aspectRatio: "16 / 9",
              maxWidth: "100%",
              overflow: "hidden",
              opacity: imageOpacity,
              mixBlendMode: "lighten",
              WebkitMaskImage: `${featherX}, ${featherY}`,
              WebkitMaskComposite: "source-in",
              maskImage: `${featherX}, ${featherY}`,
              maskComposite: "intersect",
            }}
          >
            <Img
              src={resolveAsset(image)}
              style={{
                width: "100%",
                height: "100%",
                objectFit: "cover",
                transform: `scale(${imageScale}) translateX(${imageShiftX}%)`,
              }}
            />
          </div>
          {badge ? (
            <div
              style={{
                ...chalkText,
                position: "absolute",
                left: portrait ? "4%" : "2%",
                top: "50%",
                fontSize: (portrait ? 200 : 260) * scale,
                lineHeight: 1,
                color: accentColor,
                textShadow: `0 0 ${2 * scale}px ${accentColor}, 0 0 ${14 * scale}px ${accentColor}2E`,
                opacity: badgeIn,
                transform: `translateY(-50%) scale(${0.85 + badgeIn * 0.15})`,
              }}
            >
              {badge}
            </div>
          ) : null}
        </div>
      </AbsoluteFill>
      {footer}
    </AbsoluteFill>
  );
};
