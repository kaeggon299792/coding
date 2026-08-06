import { useEffect, useState } from "react";
import { BlackHoleHeroSection } from "./components/ui/blackhole-hero-section";

type Props = {
  profileImageUrl: string;
  profileInitial: string;
  displayName: string;
  rankName: string;
  rankIconUrl: string;
};

function useNarrow(query = "(max-width: 767px)") {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const media = window.matchMedia(query);
    const sync = () => setNarrow(media.matches);
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, [query]);
  return narrow;
}

export function BlackHoleAvatarEffect(props: Props) {
  const narrow = useNarrow();
  const [imageFailed, setImageFailed] = useState(false);

  useEffect(() => {
    const mount = document.getElementById("blackhole-avatar-root");
    if (mount) mount.dataset.reactMounted = "true";
    document
      .querySelector<HTMLElement>("[data-blackhole-avatar-fallback]")
      ?.setAttribute("hidden", "");
  }, []);

  return (
    <BlackHoleHeroSection
      className="blackhole-avatar-renderer"
      transparent
      frontComposite
      focus={[0.5, 0.5]}
      scrim="none"
      distance={24}
      elevation={narrow ? -7 : -5.5}
      fov={narrow ? 50 : 44}
      glow={narrow ? 0.8 : 0.95}
      steps={narrow ? 170 : 220}
      resolution={narrow ? 0.65 : 0.78}
      maxDpr={1.5}
    >
      <span className="blackhole-avatar-image-layer">
        {props.profileImageUrl && !imageFailed ? (
          <img
            className="blackhole-avatar-image"
            src={props.profileImageUrl}
            alt={`${props.displayName} 프로필 사진`}
            referrerPolicy="no-referrer"
            onError={() => setImageFailed(true)}
          />
        ) : (
          <span className="blackhole-avatar-image blackhole-avatar-initial" aria-hidden="true">
            {props.profileInitial}
          </span>
        )}
        {props.rankIconUrl ? (
          <img
            className="blackhole-avatar-rank-badge"
            src={props.rankIconUrl}
            alt={`${props.rankName} 등급`}
          />
        ) : null}
      </span>
    </BlackHoleHeroSection>
  );
}
