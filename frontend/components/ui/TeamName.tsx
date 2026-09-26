import Image from "next/image";
import { teamColor, teamKey, teamLogoSrc } from "@/lib/teams";

/**
 * A team name with its logo, or a bar in its livery colour when no logo file
 * exists. The mark is decorative: the name beside it is what gets read out.
 */
export function TeamName({ name, className = "" }: { name: string; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <TeamMark name={name} />
      <span>{name}</span>
    </span>
  );
}

export function TeamMark({ name }: { name: string }) {
  const key = teamKey(name);
  const logo = teamLogoSrc(key);
  if (logo) {
    return (
      <Image
        src={logo}
        alt=""
        width={20}
        height={20}
        unoptimized
        className="h-5 w-5 shrink-0 object-contain"
        data-testid="team-logo"
      />
    );
  }
  return (
    <span
      aria-hidden="true"
      data-testid="team-colour"
      className="inline-block h-4 w-1 shrink-0 rounded-sm"
      style={{ backgroundColor: teamColor(key) }}
    />
  );
}
