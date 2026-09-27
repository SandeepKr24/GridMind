import type { GridDriver } from "@/lib/api/types";
import { teamKey, type TeamKey } from "@/lib/teams";

/**
 * Words about the current grid. Who is on it comes from the backend (the
 * latest race, via OpenF1); this file only adds the text the pages show.
 *
 * Bios are keyed by the three-letter code, which follows a driver between
 * teams. They stick to careers up to the end of 2025, so they do not go stale
 * as this season's results come in. A driver without one still gets a card.
 * Team facts (full name, base, first entry, titles) are from each team's
 * page on formula1.com, 2026.
 */
export const DRIVER_BIOS: Record<string, string> = {
  NOR: "Britain's Lando Norris joined McLaren as a rookie in 2019 and has driven nowhere else in Formula 1. He won his first Grand Prix in Miami in 2024 and the World Championship in 2025.",
  PIA: "Oscar Piastri won the Formula 3 and Formula 2 titles in consecutive rookie seasons, then joined McLaren in 2023. The Australian won his first Grand Prix in Hungary in 2024.",
  RUS: "George Russell won the 2018 Formula 2 title and spent three seasons at Williams before moving to Mercedes in 2022. The Briton took his first win in Brazil that year.",
  ANT: "Andrea Kimi Antonelli went from Formula 2 straight to Mercedes in 2025, taking the seat Lewis Hamilton left, as one of the youngest drivers ever to start a Grand Prix.",
  HAM: "Lewis Hamilton is a seven-time World Champion and holds the records for the most wins and pole positions. After six titles with Mercedes he moved to Ferrari in 2025.",
  LEC: "Charles Leclerc from Monaco won the 2017 Formula 2 title and has raced for Ferrari since 2019. His wins include Monza in 2019 and his home race in Monaco in 2024.",
  VER: "Max Verstappen became Formula 1's youngest winner at 18, in Spain in 2016, on his Red Bull debut. The Dutchman won four World Championships in a row, from 2021 to 2024.",
  HAD: "Isack Hadjar was runner-up in Formula 2 in 2024 and made his debut with Racing Bulls in 2025, taking a first podium at Zandvoort. The Frenchman moved up to Red Bull for 2026.",
  LAW: "New Zealand's Liam Lawson first raced in Formula 1 as a stand-in in 2023. He has driven for both Red Bull teams, starting 2025 at Red Bull before returning to Racing Bulls.",
  LIN: "Arvid Lindblad is a Red Bull junior who rose through Formula 3 and Formula 2. The British teenager made his Formula 1 debut with Racing Bulls in 2026.",
  TSU: "Yuki Tsunoda made his debut with AlphaTauri in 2021 and spent four seasons with Red Bull's junior team. The Japanese driver was promoted to Red Bull during 2025.",
  GAS: "Pierre Gasly won the 2020 Italian Grand Prix with AlphaTauri after coming up through Red Bull's junior programme. The Frenchman has led Alpine since joining it in 2023.",
  COL: "Franco Colapinto became the first Argentine in Formula 1 for over two decades when Williams gave him a mid-season debut in 2024. He moved to Alpine during 2025.",
  OCO: "Esteban Ocon won the 2021 Hungarian Grand Prix for Alpine. The Frenchman, who first raced in Formula 1 in 2016, joined Haas in 2025.",
  BEA: "Oliver Bearman scored points on a surprise debut for Ferrari in Saudi Arabia in 2024, standing in for Carlos Sainz. The Briton has raced full time for Haas since 2025.",
  HUL: "Nico Hülkenberg made his debut in 2010 and has one of the longest careers on the grid. The German took his first podium at Silverstone in 2025, in his 239th start.",
  BOR: "Gabriel Bortoleto won the Formula 3 title in 2023 and Formula 2 in 2024, both as a rookie. The Brazilian made his debut in 2025 with the team that became Audi.",
  SAI: "Carlos Sainz won four Grands Prix with Ferrari, the first at Silverstone in 2022. The Spaniard joined Williams in 2025 and gave the team a podium in Baku that year.",
  ALB: "Alexander Albon races under the Thai flag. After starts with Toro Rosso and Red Bull, he joined Williams in 2022 and has become one of the team's leaders.",
  ALO: "Fernando Alonso won the World Championship with Renault in 2005 and 2006 and has started more Grands Prix than anyone. The Spaniard has driven for Aston Martin since 2023.",
  STR: "Canada's Lance Stroll took a podium in his rookie season with Williams in 2017 and a pole position in Turkey in 2020. He has driven for Aston Martin since the team took that name in 2021.",
  BOT: "Valtteri Bottas won ten Grands Prix alongside Lewis Hamilton at Mercedes. After three seasons at Sauber and a year as Mercedes' reserve, the Finn returned to racing with Cadillac.",
  PER: "Mexico's Sergio Pérez won six Grands Prix, most of them with Red Bull, where he twice helped win the Constructors' title. He returned after a year away to race for Cadillac.",
};

export interface TeamInfo {
  fullName: string;
  bio: string;
}

export const TEAM_INFO: Partial<Record<TeamKey, TeamInfo>> = {
  mercedes: {
    fullName: "Mercedes-AMG PETRONAS Formula One Team",
    bio: "Based in Brackley, England. Mercedes won eight Constructors' Championships in a row from 2014 to 2021, the longest run in the sport's history.",
  },
  ferrari: {
    fullName: "Scuderia Ferrari HP",
    bio: "Based in Maranello, Italy. Ferrari is the only team to have raced in every season since the championship began in 1950, and holds a record 16 Constructors' titles.",
  },
  mclaren: {
    fullName: "McLaren Mastercard F1 Team",
    bio: "Based in Woking, England. Founded by Bruce McLaren, the team first raced in 1966 and has won ten Constructors' titles, including 2024 and 2025.",
  },
  red_bull: {
    fullName: "Oracle Red Bull Racing",
    bio: "Based in Milton Keynes, England. Red Bull has won six Constructors' titles, and from 2026 builds its own power units with Ford.",
  },
  rb: {
    fullName: "Visa Cash App Racing Bulls Formula One Team",
    bio: "Based in Faenza, Italy. Red Bull's second team began life as Minardi in 1985 and won races as Toro Rosso and AlphaTauri, both at Monza.",
  },
  alpine: {
    fullName: "BWT Alpine Formula One Team",
    bio: "Based in Enstone, England, the team behind Benetton's and Renault's titles. Alpine races with Mercedes power units from 2026.",
  },
  haas: {
    fullName: "TGR Haas F1 Team",
    bio: "Based in Kannapolis, North Carolina. Haas joined in 2016 as the first American team in three decades and works closely with Ferrari and Toyota Gazoo Racing.",
  },
  audi: {
    fullName: "Audi Revolut F1 Team",
    bio: "Based in Hinwil, Switzerland, in the former Sauber factory. Audi made its Formula 1 debut in 2026 as a full works team with its own power unit.",
  },
  williams: {
    fullName: "Atlassian Williams F1 Team",
    bio: "Based in Grove, England. Founded by Frank Williams and Patrick Head, the team first raced in 1978 and won nine Constructors' titles.",
  },
  aston_martin: {
    fullName: "Aston Martin Aramco Formula One Team",
    bio: "Based at Silverstone, England. Aston Martin races with Honda works power units from 2026, with Adrian Newey leading the team.",
  },
  cadillac: {
    fullName: "Cadillac Formula 1 Team",
    bio: "The grid's newest team, backed by General Motors, joined in 2026 as the eleventh entry, with operations in the United States and at Silverstone and Ferrari power units.",
  },
};

export interface GridTeam {
  /** The team name the backend sent, e.g. "Red Bull Racing". */
  name: string;
  key: TeamKey | null;
  colour: string | null;
  drivers: GridDriver[];
}

/** Teams in the order of their lowest car number, each with its drivers. */
export function groupTeams(drivers: GridDriver[]): GridTeam[] {
  const teams = new Map<string, GridTeam>();
  for (const driver of [...drivers].sort((a, b) => a.number - b.number)) {
    const team = teams.get(driver.team_name) ?? {
      name: driver.team_name,
      key: teamKey(driver.team_name),
      colour: driver.team_colour,
      drivers: [],
    };
    teams.set(driver.team_name, { ...team, drivers: [...team.drivers, driver] });
  }
  return [...teams.values()];
}

export function driverName(driver: GridDriver): string {
  return [driver.first_name, driver.last_name].filter(Boolean).join(" ");
}
