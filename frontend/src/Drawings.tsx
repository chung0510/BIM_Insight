import { useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  Box,
  Check,
  FileText,
  Maximize2,
  Minus,
  Plus,
  Ruler,
  Search,
} from "lucide-react";
import type { ModelVariant } from "./models";

type DrawingKind =
  | "plan"
  | "elevation"
  | "foundation"
  | "frame"
  | "electrical"
  | "plumbing"
  | "perspective";
export const drawingCategories = [
  "Tất cả",
  "Kiến trúc",
  "Kết cấu",
  "Cơ điện",
  "Phối cảnh 3D",
] as const;
export const drawings: {
  id: string;
  title: string;
  category: string;
  kind: DrawingKind;
  detail: string;
  model: ModelVariant;
  image?: string;
}[] = [
  {
    id: "KT-01",
    title: "Mặt bằng tầng 1",
    category: "Kiến trúc",
    kind: "plan",
    detail: "Tổ chức không gian · Kích thước · Cửa",
    model: "savoye",
  },
  {
    id: "KT-02",
    title: "Mặt đứng chính",
    category: "Kiến trúc",
    kind: "elevation",
    detail: "Cao độ · Hình khối · Vật liệu mặt tiền",
    model: "robie",
  },
  {
    id: "KC-01",
    title: "Mặt bằng móng",
    category: "Kết cấu",
    kind: "foundation",
    detail: "Lưới trục · Móng đơn · Giằng móng",
    model: "farnsworth",
  },
  {
    id: "KC-02",
    title: "Khung dầm — cột",
    category: "Kết cấu",
    kind: "frame",
    detail: "Hệ khung · Sàn tầng · Đường truyền lực",
    model: "glass",
  },
  {
    id: "ME-01",
    title: "Mặt bằng điện chiếu sáng",
    category: "Cơ điện",
    kind: "electrical",
    detail: "Đèn · Công tắc · Tuyến dây điện",
    model: "stahl",
  },
  {
    id: "ME-02",
    title: "Sơ đồ cấp thoát nước",
    category: "Cơ điện",
    kind: "plumbing",
    detail: "Nước lạnh · Nước nóng · Thoát nước",
    model: "tugendhat",
  },
  {
    id: "PC-01",
    title: "Phối cảnh Fallingwater",
    category: "Phối cảnh 3D",
    kind: "perspective",
    detail: "Mô hình cảm hứng · Hiên vươn · Thác nước",
    model: "fallingwater",
    image: "/images/residences/fallingwater.webp",
  },
  {
    id: "PC-02",
    title: "Phối cảnh Red House",
    category: "Phối cảnh 3D",
    kind: "perspective",
    detail: "Mô hình cảm hứng · Gạch đỏ · Mái dốc",
    model: "red-house",
    image: "/images/residences/red-house.webp",
  },
];
export type Drawing = (typeof drawings)[number];

function RoomPlan({ detailed = true }: { detailed?: boolean }) {
  return (
    <g fill="none" stroke="currentColor" strokeWidth="3">
      <path
        d="M245 490V140H755V490H605M535 490H245M520 140V285M520 340V490M245 320H440M485 320H755M650 320V490"
        strokeWidth={detailed ? 9 : 4}
      />
      <g strokeWidth="1.2">
        <path d="M520 285h55a55 55 0 0 1-55 55M440 320v-45a45 45 0 0 1 45 45M535 490v-70a70 70 0 0 1 70 70" />
        <path
          d="M285 134H385V146H285ZM245 375h-6v75h12v-75ZM590 134H695V146H590ZM749 190h12v70h-12Z"
          fill="#e6eee8"
          stroke="#477864"
          strokeWidth="2"
        />
        <path d="M550 350H620V465H550ZM550 362H620M550 374H620M550 386H620M550 398H620M550 410H620M550 422H620M550 434H620M550 446H620M550 458H620M584 458V354M579 364l5-10 5 10" />
      </g>
      {detailed && (
        <g strokeWidth="1.3">
          <rect x="268" y="360" width="42" height="94" rx="4" />
          <rect x="314" y="411" width="85" height="42" rx="4" />
          <rect x="337" y="365" width="47" height="29" rx="3" />
          <rect x="280" y="158" width="180" height="31" />
          <rect x="280" y="158" width="31" height="95" />
          <circle cx="416" cy="243" r="28" />
          <path d="M405 205h22M405 281h22M378 231v23M454 231v23" />
          <rect x="569" y="166" width="104" height="116" rx="2" />
          <path d="M569 193H673M574 172h42v16h-42ZM625 172h42v16h-42Z" />
          <rect x="680" y="354" width="46" height="26" rx="4" />
          <ellipse cx="704" cy="432" rx="18" ry="25" />
        </g>
      )}
      {detailed && (
        <g fill="currentColor" stroke="none" textAnchor="middle" fontSize="12">
          <text x="409" y="438">
            PHÒNG KHÁCH
          </text>
          <text x="404" y="301">
            BẾP + ĂN
          </text>
          <text x="635" y="307">
            PHÒNG NGỦ
          </text>
          <text x="704" y="479">
            WC
          </text>
          <text x="584" y="480" fontSize="9">
            CẦU THANG
          </text>
        </g>
      )}
    </g>
  );
}

function Axes({ foundation = false }: { foundation?: boolean }) {
  const xs = [245, 500, 755],
    ys = foundation ? [155, 320, 485] : [140, 320, 490];
  return (
    <g stroke="#758378" strokeWidth=".8" fill="none">
      <g strokeDasharray="9 4 2 4">
        {xs.map((x) => (
          <path key={x} d={`M${x} 92V535`} />
        ))}
        {ys.map((y) => (
          <path key={y} d={`M185 ${y}H810`} />
        ))}
      </g>
      {xs.map((x, i) => (
        <g key={x}>
          <circle cx={x} cy="82" r="11" fill="#faf8f1" />
          <text
            x={x}
            y="86"
            textAnchor="middle"
            fill="#405b4c"
            stroke="none"
            fontSize="11"
          >
            {i + 1}
          </text>
        </g>
      ))}
      {ys.map((y, i) => (
        <g key={y}>
          <circle cx="174" cy={y} r="11" fill="#faf8f1" />
          <text
            x="174"
            y={y + 4}
            textAnchor="middle"
            fill="#405b4c"
            stroke="none"
            fontSize="11"
          >
            {String.fromCharCode(65 + i)}
          </text>
        </g>
      ))}
    </g>
  );
}

function Dimensions() {
  return (
    <g fill="none" stroke="#7c8779" strokeWidth=".8">
      <path d="M245 512V563M755 512V563M245 548H755M239 554l12-12M749 554l12-12M790 140H833M790 490H833M818 140V490M812 146l12-12M812 496l12-12" />
      <g fill="#405b4c" stroke="none" fontSize="12" textAnchor="middle">
        <text x="500" y="543">
          8 000
        </text>
        <text transform="translate(813 315) rotate(-90)">6 000</text>
      </g>
    </g>
  );
}

function Elevation({ structural = false }: { structural?: boolean }) {
  return (
    <g stroke="currentColor" fill="none">
      <path
        d="M216 510H786M245 505V230M500 505V230M755 505V230M245 230H755M245 365H755M245 500H755"
        strokeWidth={structural ? 9 : 2}
      />
      {structural ? (
        <>
          <path
            d="M223 510h44v24h-44ZM478 510h44v24h-44ZM733 510h44v24h-44Z"
            strokeWidth="3"
          />
          <path d="M205 542h90M455 542h90M705 542h90" strokeWidth="1" />
          {[245, 500, 755].map((x) => (
            <g key={x}>
              <path
                d={`M${x} 155V550`}
                stroke="#8b9387"
                strokeDasharray="8 4 2 4"
                strokeWidth="1"
              />
              <circle cx={x} cy="140" r="12" />
              <text
                x={x}
                y="144"
                textAnchor="middle"
                fill="currentColor"
                stroke="none"
                fontSize="11"
              >
                {[245, 500, 755].indexOf(x) + 1}
              </text>
            </g>
          ))}
        </>
      ) : (
        <>
          <path
            d="M220 230 500 125 780 230ZM245 230H755M245 238H755"
            strokeWidth="2"
          />
          <path d="M245 229 500 137 755 229" stroke="#ad4b30" />
          <path
            d="M535 500V390H600V500M285 270H420V345H285ZM545 270H680V345H545ZM285 390H420V480H285ZM650 390H715V480H650Z"
            strokeWidth="2"
          />
          {[310, 345, 380, 570, 605, 640].map((x) => (
            <path key={x} d={`M${x} 270V345`} strokeWidth="1" />
          ))}
          <path d="M285 307H420M545 307H680M270 355H720V382H270ZM270 369H720" />
          <path d="M256 500v12h490v-12M245 518H755" />
          <g stroke="#9b7051" strokeWidth=".7">
            {Array.from({ length: 20 }, (_, i) => (
              <path key={i} d={`M${290 + i * 20} 358V378`} />
            ))}
          </g>
        </>
      )}
      <g stroke="#758378" strokeWidth=".8">
        <path d="M800 230H855M800 365H855M800 500H855M833 230V500M827 236l12-12M827 371l12-12M827 506l12-12" />
        <g fill="#405b4c" stroke="none" fontSize="11">
          <text x="860" y="234">
            +6.600
          </text>
          <text x="860" y="369">
            +3.300
          </text>
          <text x="860" y="504">
            ±0.000
          </text>
          <text transform="translate(828 305) rotate(-90)">3 300</text>
          <text transform="translate(828 440) rotate(-90)">3 300</text>
        </g>
      </g>
      <text
        x="500"
        y="582"
        textAnchor="middle"
        fill="currentColor"
        stroke="none"
        fontSize="13"
      >
        {structural
          ? "KHUNG TRỤC B — SƠ ĐỒ CHỊU LỰC"
          : "MẶT ĐỨNG CHÍNH — HƯỚNG NAM"}
      </text>
    </g>
  );
}

function Foundation() {
  return (
    <>
      <Axes foundation />
      <g fill="none" stroke="currentColor">
        {[155, 320, 485].map((y) => (
          <g key={y}>
            <path
              d={`M245 ${y - 8}H755V${y + 8}H245Z`}
              fill="#e9e5da"
              strokeWidth="1.3"
            />
          </g>
        ))}
        {[245, 500, 755].map((x) => (
          <path
            key={x}
            d={`M${x - 8} 155V485H${x + 8}V155Z`}
            fill="#e9e5da"
            strokeWidth="1.3"
          />
        ))}
        {[245, 500, 755].flatMap((x, ix) =>
          [155, 320, 485].map((y, iy) => (
            <g key={`${x}-${y}`}>
              <rect
                x={x - 36}
                y={y - 32}
                width="72"
                height="64"
                fill="#f1ede1"
                strokeWidth="1.8"
              />
              <rect
                x={x - 24}
                y={y - 22}
                width="48"
                height="44"
                strokeWidth=".7"
              />
              <path
                d={`M${x - 34} ${y - 30}l68 60M${x + 34} ${y - 30}l-68 60`}
                stroke="#9a9b87"
                strokeWidth=".7"
              />
              <rect x={x - 9} y={y - 9} width="18" height="18" fill="#526b57" />
              <text
                x={x + 44}
                y={y - 19}
                stroke="none"
                fill="currentColor"
                fontSize="11"
              >
                M{ix === 1 && iy === 1 ? 2 : 1}
              </text>
            </g>
          )),
        )}
        <text
          x="500"
          y="591"
          textAnchor="middle"
          stroke="none"
          fill="currentColor"
          fontSize="12"
        >
          M1: MÓNG GÓC / BIÊN · M2: MÓNG GIỮA · GM: GIẰNG MÓNG
        </text>
      </g>
      <Dimensions />
    </>
  );
}

function Services({ plumbing }: { plumbing: boolean }) {
  return (
    <>
      <g opacity=".45">
        <RoomPlan detailed={false} />
      </g>
      {plumbing ? (
        <g fill="none" strokeWidth="3">
          <path d="M200 175H708V438M285 175V218M685 175V358" stroke="#377caa" />
          <path d="M200 192H691V365M300 192V218" stroke="#b9553b" />
          <path
            d="M708 438V466H731V535M285 241V272H731V466"
            stroke="#47785b"
            strokeWidth="4"
          />
          <g stroke="#627364" strokeWidth="1.2">
            <rect x="270" y="216" width="45" height="28" rx="3" />
            <rect x="672" y="352" width="42" height="25" rx="3" />
            <ellipse cx="708" cy="416" rx="19" ry="24" />
            <path d="M190 164h20v38h-20Z" />
            <text
              x="200"
              y="152"
              textAnchor="middle"
              fill="#405b4c"
              stroke="none"
              fontSize="10"
            >
              ĐỒNG HỒ
            </text>
          </g>
          <g fill="#f8f5ec" stroke="#377caa" strokeWidth="2">
            {[
              [285, 175],
              [685, 175],
              [708, 270],
            ].map(([x, y]) => (
              <circle cx={x} cy={y} r="5" key={`${x}-${y}`} />
            ))}
          </g>
          <path d="m724 520 7 14 7-14" stroke="#47785b" strokeWidth="2" />
          <g fontSize="11" stroke="none" fill="#405b4c">
            <text x="330" y="232">
              CHẬU BẾP
            </text>
            <text x="603" y="405">
              WC
            </text>
            <text x="742" y="527">
              THOÁT
            </text>
          </g>
        </g>
      ) : (
        <g fill="none">
          <path
            d="M266 450V160H730V450M266 450H350V410M730 450H700V400"
            stroke="#5c8660"
            strokeDasharray="5 4"
            strokeWidth="2"
          />
          <path
            d="M545 470V300H380V225M545 300H635V225M545 410H380M635 300V395H700"
            stroke="#b18b32"
            strokeWidth="2"
            strokeDasharray="8 4"
          />
          {[
            [380, 225],
            [635, 225],
            [380, 410],
            [700, 395],
          ].map(([x, y]) => (
            <g key={`${x}-${y}`} stroke="#92722b" strokeWidth="1.8">
              <circle cx={x} cy={y} r="15" fill="#efe6be" />
              <path
                d={`M${x - 10} ${y - 10}l20 20M${x + 10} ${y - 10}l-20 20`}
              />
            </g>
          ))}
          {[
            [490, 304],
            [535, 360],
            [662, 337],
          ].map(([x, y]) => (
            <g key={`${x}-${y}`} stroke="#92722b" strokeWidth="1.5">
              <circle cx={x} cy={y} r="5" />
              <path d={`M${x + 4} ${y - 4}l9-9`} />
            </g>
          ))}
          <rect
            x="532"
            y="452"
            width="27"
            height="35"
            fill="#e9e1cb"
            stroke="#92722b"
          />
          <text
            x="546"
            y="506"
            fill="#405b4c"
            fontSize="10"
            textAnchor="middle"
          >
            TỦ ĐIỆN
          </text>
          <g fill="#405b4c" fontSize="10">
            <text x="399" y="230">
              Đ1
            </text>
            <text x="654" y="230">
              Đ2
            </text>
            <text x="399" y="415">
              Đ3
            </text>
          </g>
        </g>
      )}
      <Dimensions />
      <g transform="translate(220 590)" fontSize="10" fill="#405b4c">
        <path
          d="M0 0H28"
          stroke={plumbing ? "#377caa" : "#b18b32"}
          strokeWidth="2"
        />
        <text x="36" y="4">
          {plumbing ? "NƯỚC LẠNH" : "CHIẾU SÁNG"}
        </text>
        <path
          d="M180 0H208"
          stroke={plumbing ? "#b9553b" : "#5c8660"}
          strokeWidth="2"
        />
        <text x="216" y="4">
          {plumbing ? "NƯỚC NÓNG" : "ĐIỆN ĐỘNG LỰC"}
        </text>
        {plumbing && (
          <>
            <path d="M370 0H398" stroke="#47785b" strokeWidth="3" />
            <text x="406" y="4">
              THOÁT NƯỚC
            </text>
          </>
        )}
      </g>
    </>
  );
}

function DrawingSheet({ drawing }: { drawing: Drawing }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 1000 700"
      role="img"
      aria-label={`${drawing.id} — ${drawing.title}`}
      className="technical-sheet"
      style={{ fontFamily: "Be Vietnam Pro, sans-serif", color: "#354d3f" }}
    >
      <rect width="1000" height="700" fill="#faf8f1" />
      <rect
        x="22"
        y="22"
        width="956"
        height="656"
        fill="none"
        stroke="#a4ab98"
        strokeWidth="1"
      />
      <path
        d="M22 72H978M22 620H978M620 620V678M840 620V678"
        fill="none"
        stroke="#a4ab98"
      />
      <text x="44" y="51" fontSize="16" fill="#354d3f" fontWeight="600">
        xưởng học / hồ sơ nhà ở
      </text>
      <text x="954" y="50" fontSize="10" textAnchor="end" fill="#7b806e">
        BẢN VẼ MINH HỌA HỌC TẬP
      </text>
      {drawing.kind === "plan" && (
        <>
          <Axes />
          <RoomPlan />
          <Dimensions />
          <g transform="translate(870 160)" stroke="#405b4c" fill="none">
            <path d="M0 35V0l-7 16h14L0 0" />
            <text
              x="0"
              y="-9"
              textAnchor="middle"
              fill="#405b4c"
              stroke="none"
              fontSize="12"
            >
              B
            </text>
          </g>
        </>
      )}
      {drawing.kind === "elevation" && <Elevation />}
      {drawing.kind === "foundation" && <Foundation />}
      {drawing.kind === "frame" && <Elevation structural />}
      {(drawing.kind === "electrical" || drawing.kind === "plumbing") && (
        <Services plumbing={drawing.kind === "plumbing"} />
      )}
      <text x="44" y="645" fontSize="10" fill="#7b806e">
        CÔNG TRÌNH / NHÀ Ở HAI TẦNG
      </text>
      <text x="44" y="666" fontSize="15" fill="#354d3f" fontWeight="500">
        {drawing.title.toLocaleUpperCase("vi")}
      </text>
      <text x="638" y="644" fontSize="9" fill="#7b806e">
        BỘ MÔN / {drawing.category.toLocaleUpperCase("vi")}
      </text>
      <text x="638" y="665" fontSize="10" fill="#354d3f">
        TỈ LỆ THAM KHẢO 1:100 · ĐƠN VỊ mm
      </text>
      <text x="860" y="644" fontSize="9" fill="#7b806e">
        SỐ HIỆU BẢN VẼ
      </text>
      <text x="860" y="668" fontSize="21" fill="#ad4b30" fontWeight="600">
        {drawing.id}
      </text>
    </svg>
  );
}

export function DrawingLibrary({
  query,
  onOpen,
  onOpenModel,
}: {
  query: string;
  onOpen: (drawing: Drawing) => void;
  onOpenModel: (model: ModelVariant) => void;
}) {
  const [category, setCategory] = useState("Tất cả");
  const filtered = drawings.filter(
    (drawing) =>
      (category === "Tất cả" || drawing.category === category) &&
      `${drawing.id} ${drawing.title} ${drawing.category}`
        .toLocaleLowerCase("vi")
        .includes(query.trim().toLocaleLowerCase("vi")),
  );
  return (
    <section className="drawing-library">
      <div className="library-banner">
        <div className="library-banner-icon">
          <Ruler size={28} />
        </div>
        <div>
          <span className="section-index">BẢN VẼ MẪU / BỘ SƯU TẬP NHÀ Ở</span>
          <h2>Những nét vẽ. Những không gian.</h2>
          <p>
            Thử thao tác với bản vẽ 2D độc lập. Khám phá các nhà ở 3D để tham khảo hình khối và vật liệu.
          </p>
        </div>
        <span className="library-total">
          <strong>08</strong> bản vẽ & phối cảnh
        </span>
      </div>
      <div className="drawing-filters">
        <div className="filters" aria-label="Bộ môn bản vẽ">
          {drawingCategories.map((item) => (
            <button
              key={item}
              aria-pressed={item === category}
              className={item === category ? "selected" : ""}
              onClick={() => setCategory(item)}
            >
              {item}
            </button>
          ))}
        </div>
        <span>{String(filtered.length).padStart(2, "0")} tài liệu</span>
      </div>
      <div className="drawing-grid">
        {filtered.map((drawing) => (
          <article className="drawing-card" key={drawing.id}>
            <button
              className={`drawing-thumbnail ${drawing.image ? "drawing-render" : ""}`}
              aria-label={`Xem bản vẽ: ${drawing.title}`}
              onClick={() => onOpen(drawing)}
            >
              {drawing.image ? (
                <img
                  src={drawing.image}
                  width="768"
                  height="512"
                  loading="lazy"
                  alt={drawing.title}
                />
              ) : (
                <DrawingSheet drawing={drawing} />
              )}
              <span className="drawing-open">
                <Maximize2 size={17} />
                Mở bản vẽ
              </span>
            </button>
            <div className="drawing-card-body">
              <div className="drawing-card-meta">
                <span>{drawing.category}</span>
                <span>{drawing.id}</span>
              </div>
              <h3>{drawing.title}</h3>
              <p>{drawing.detail}</p>
              <div className="drawing-card-footer">
                <span>
                  <FileText size={13} />
                  {drawing.image ? "Phối cảnh kết xuất" : "Bản vẽ vector"}
                </span>
                <button
                  aria-label={`Mở mô hình từ ${drawing.id}`}
                  onClick={() => onOpenModel(drawing.model)}
                >
                  <Box size={15} />
                  Xem 3D
                  <ArrowRight size={14} />
                </button>
              </div>
            </div>
          </article>
        ))}
      </div>
      {filtered.length === 0 && (
        <div className="empty-state">
          <Search size={28} />
          <h3>Chưa tìm thấy bản vẽ phù hợp.</h3>
          <p>Thử tên bộ môn, “mặt bằng” hoặc mã “KT-01”.</p>
        </div>
      )}
      <p className="drawing-library-note">
        <Check size={15} /> Bản vẽ minh họa để học cách đọc hồ sơ. Kích thước và
        cấu tạo không dùng cho thi công.
      </p>
    </section>
  );
}

export function DrawingViewer({
  drawing,
  onOpenModel,
}: {
  drawing: Drawing;
  onOpenModel: (model: ModelVariant) => void;
}) {
  const [zoom, setZoom] = useState(1);
  const sheet = useRef<HTMLDivElement>(null);
  function download() {
    const link = document.createElement("a");
    if (drawing.image) {
      link.href = drawing.image;
      link.download = `${drawing.id}.webp`;
      link.click();
      return;
    }
    const svg = sheet.current?.querySelector("svg");
    if (!svg) return;
    const clone = svg.cloneNode(true) as SVGElement;
    clone.setAttribute("width", "1000");
    clone.setAttribute("height", "700");
    const url = URL.createObjectURL(
      new Blob(['<?xml version="1.0" encoding="UTF-8"?>\n', clone.outerHTML], {
        type: "image/svg+xml;charset=utf-8",
      }),
    );
    link.href = url;
    link.download = `${drawing.id}.svg`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <div className="drawing-viewer">
      <div className="drawing-viewer-toolbar">
        <span>
          <FileText size={17} />
          {drawing.id}
          <span className="drawing-toolbar-category">{drawing.category}</span>
        </span>
        <div>
          <button
            aria-label="Thu nhỏ bản vẽ"
            disabled={zoom <= 0.75}
            onClick={() => setZoom(Math.max(0.75, zoom - 0.25))}
          >
            <Minus size={17} />
          </button>
          <output aria-label="Tỉ lệ phóng to">{Math.round(zoom * 100)}%</output>
          <button
            aria-label="Phóng to bản vẽ"
            disabled={zoom >= 2.5}
            onClick={() => setZoom(Math.min(2.5, zoom + 0.25))}
          >
            <Plus size={17} />
          </button>
          <button aria-label="Vừa khung bản vẽ" onClick={() => setZoom(1)}>
            <Maximize2 size={17} />
          </button>
        </div>
        <button
          onClick={download}
          aria-label={drawing.image ? "Tải phối cảnh" : "Tải bản vẽ SVG"}
        >
          <ArrowDownToLine size={16} />
          <span>Tải {drawing.image ? "phối cảnh" : "SVG"}</span>
        </button>
      </div>
      <div
        className="drawing-viewport"
        tabIndex={0}
        aria-label="Vùng xem bản vẽ, có thể cuộn khi phóng to"
      >
        <div ref={sheet} style={{ width: `${zoom * 100}%` }}>
          {drawing.image ? (
            <img
              src={drawing.image}
              alt={drawing.title}
              width="1536"
              height="1024"
            />
          ) : (
            <DrawingSheet drawing={drawing} />
          )}
        </div>
      </div>
      <div className="drawing-viewer-bottom">
        <p>
          <strong>{drawing.detail}</strong>
          <span>
            Bản vẽ mô phỏng độc lập. Bộ nhà 3D bên cạnh dùng để tham khảo hình khối.
          </span>
        </p>
        <button
          className="button button-primary"
          onClick={() => onOpenModel(drawing.model)}
        >
          Xem nhà ở tham khảo
          <Box size={17} />
        </button>
      </div>
    </div>
  );
}
