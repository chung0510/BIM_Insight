const residences = [
  { id: "fallingwater", name: "Fallingwater", location: "Pennsylvania, Hoa Kỳ", architect: "Frank Lloyd Wright", description: "Những hiên nhà vươn trên thác nước và đá tự nhiên.", source: "https://fallingwater.org/media-resources/fallingwater-facts/" },
  { id: "savoye", name: "Villa Savoye", location: "Poissy, Pháp", architect: "Le Corbusier · Pierre Jeanneret", description: "Khối nhà trắng trên hàng cột, cửa sổ dài và vườn mái.", source: "https://www.villa-savoye.fr/decouvrir/les-5-points-de-l-architecture-moderne-selon-le-corbusier" },
  { id: "farnsworth", name: "Farnsworth House", location: "Illinois, Hoa Kỳ", architect: "Ludwig Mies van der Rohe", description: "Hai mặt phẳng trắng nâng một không gian kính giữa thiên nhiên.", source: "https://edithfarnsworthhouse.org/history-farnsworth-house/" },
  { id: "glass", name: "The Glass House", location: "Connecticut, Hoa Kỳ", architect: "Philip Johnson", description: "Khung thép đen, bốn mặt kính và lõi gạch tròn.", source: "https://theglasshouse.org/explore/the-glass-house/" },
  { id: "tugendhat", name: "Villa Tugendhat", location: "Brno, Cộng hòa Séc", architect: "Ludwig Mies van der Rohe", description: "Những lớp không gian trắng mở ra khu vườn trên sườn dốc.", source: "https://whc.unesco.org/en/list/1052/" },
  { id: "eames", name: "Eames House", location: "California, Hoa Kỳ", architect: "Charles & Ray Eames", description: "Khung thép mảnh và những mảng màu giữa vườn cây.", source: "https://eamesfoundation.org/work/case-study-house-8/" },
  { id: "stahl", name: "Stahl House", location: "Los Angeles, Hoa Kỳ", architect: "Pierre Koenig", description: "Nhà kính hình chữ L ôm hồ nước trên sườn đồi.", source: "https://stahlhouse.com/" },
  { id: "robie", name: "Robie House", location: "Chicago, Hoa Kỳ", architect: "Frank Lloyd Wright", description: "Gạch ấm, mái đua rộng và những đường ngang của Prairie.", source: "https://flwright.org/explore/robie-house" },
  { id: "schroder", name: "Rietveld Schröder House", location: "Utrecht, Hà Lan", architect: "Gerrit Rietveld · Truus Schröder", description: "Những mặt phẳng trắng, đen và màu cơ bản của De Stijl.", source: "https://www.rietveldschroderhuis.nl/en" },
  { id: "malaparte", name: "Casa Malaparte", location: "Capri, Ý", architect: "Ngôi nhà của Curzio Malaparte", description: "Khối đỏ trên vách đá, thang lớn dẫn lên sân mái nhìn ra biển.", source: "https://www.italia.it/it/campania/cosa-fare/vacanza-da-sogno-capri" },
  { id: "carre", name: "Maison Louis Carré", location: "Bazoches-sur-Guyonne, Pháp", architect: "Alvar Aalto", description: "Mái dốc thoải, gạch trắng và gỗ trong khu vườn yên tĩnh.", source: "https://www.alvaraalto.fi/en/architecture/maison-louis-carre/" },
  { id: "barragan", name: "Casa Luis Barragán", location: "Mexico City, Mexico", architect: "Luis Barragán", description: "Tường dày, sân vườn và những mặt phẳng màu dưới ánh nắng.", source: "https://casaluisbarragan.org/" },
  { id: "gilardi", name: "Casa Gilardi", location: "Mexico City, Mexico", architect: "Luis Barragán", description: "Sân trong, hành lang vàng và khoảng nước xanh bên tường hồng.", source: "https://casagilardi.mx/" },
  { id: "red-house", name: "Red House", location: "London, Vương quốc Anh", architect: "Philip Webb · William Morris", description: "Gạch đỏ, mái dốc và khu vườn mang tinh thần Arts & Crafts.", source: "https://www.nationaltrust.org.uk/visit/london/red-house" },
] as const;

export type ModelVariant = (typeof residences)[number]["id"];
export const models = residences.map(home => ({ ...home, image: `/images/residences/${home.id}.webp`, discipline: "Kiến trúc" }));
export function modelInfo(variant: ModelVariant) { return models.find(home => home.id === variant) ?? models[0]; }

export const screenModels = {
  login: "fallingwater", register: "savoye", setup: "farnsworth",
  admin: "glass", teacher: "tugendhat", student: "eames", user: "stahl",
  inspection: "robie", shared: "schroder", drawings: "malaparte", models: "carre",
  notes: "barragan", accounts: "gilardi", account: "red-house",
} as const satisfies Record<string, ModelVariant>;
