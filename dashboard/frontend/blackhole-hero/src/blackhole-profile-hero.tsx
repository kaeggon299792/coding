import { useEffect, useState } from "react";
import { BlackHoleHeroSection } from "./components/ui/blackhole-hero-section";

type Props = {
  profileImageUrl: string;
  profileInitial: string;
  displayName: string;
  rankName: string;
  rankDescription: string;
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

export function BlackHoleProfileHero(props: Props) {
  const narrow = useNarrow();
  const [imageFailed, setImageFailed] = useState(false);

  useEffect(() => {
    const mount = document.getElementById("blackhole-profile-root");
    if (mount) mount.dataset.reactMounted = "true";
    document.querySelector<HTMLElement>("[data-blackhole-fallback]")?.setAttribute("hidden", "");
  }, []);

  return (
    <section className="blackhole-profile-hero" aria-label="프로필">
      <BlackHoleHeroSection
        focus={narrow ? [0.5, 0.76] : [0.72, 0.46]}
        scrim={narrow ? "top" : "left"}
        scrimStrength={0.9}
        distance={24}
        elevation={narrow ? -7 : -5.5}
        fov={narrow ? 58 : 42}
        glow={narrow ? 0.85 : 1}
        steps={narrow ? 200 : 300}
        resolution={narrow ? 0.6 : 0.7}
      >
        <div className="blackhole-profile-copy">
          <div className="blackhole-profile-identity">
            <span className="blackhole-profile-avatar">
              {props.profileImageUrl && !imageFailed ? (
                <img src={props.profileImageUrl} alt={`${props.displayName} 프로필 사진`} referrerPolicy="no-referrer" onError={() => setImageFailed(true)} />
              ) : (
                <span aria-hidden="true">{props.profileInitial}</span>
              )}
              {props.rankIconUrl ? <img className="blackhole-profile-badge" src={props.rankIconUrl} alt={`${props.rankName} 등급`} /> : null}
            </span>
            <div>
              <p className="blackhole-profile-kicker">CASINO IN / ACCOUNT</p>
              <h1>안녕하세요,<br /><strong>{props.displayName}</strong>님</h1>
              <p className="blackhole-profile-rank"><b>{props.rankName}</b>{props.rankDescription ? ` · ${props.rankDescription}` : ""}</p>
            </div>
          </div>
        </div>
      </BlackHoleHeroSection>
    </section>
  );
}
