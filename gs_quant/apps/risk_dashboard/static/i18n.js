/*
 * Risk Analytics Dashboard: translations.
 * Copyright 2026 Senanur Çetin. Licensed under the Apache License, Version 2.0.
 *
 * The page is written in English. t('English text', { name: value }) looks the text up in the Turkish table below and
 * falls back to the English text, so a missing translation shows English, never nothing. {name} stands for a value and
 * **text** for a strong part, so a translation can put both wherever its word order needs them. Text that comes from the
 * server (assumptions and error messages) is matched against the patterns at the end; what is not matched stays English.
 */
(() => {
  'use strict';
  const STORAGE_KEY = 'risk-app-language';
  const LANGUAGES = ['en', 'tr'];

  const TR = {
    "Risk Analytics Dashboard": "Risk Analizi Panosu",
    "Skip to results": "Sonuçlara geç",
    "Access token required": "Erişim anahtarı gerekli",
    "This server asks for an access token. It is kept for this browser tab only.": "Bu sunucu bir erişim anahtarı istiyor. Anahtar yalnızca bu tarayıcı sekmesinde tutulur.",
    "Access token": "Erişim anahtarı",
    "Unlock": "Kilidi aç",
    "Data and model": "Veri ve model",
    "Analyse": "Analiz",
    "One return series": "Tek bir getiri serisi",
    "A portfolio of assets": "Varlık portföyü",
    "Upload a CSV of several assets": "Birden çok varlığın CSV dosyasını yükle",
    "Load a sample portfolio": "Örnek portföy yükle",
    "Weights": "Ağırlıklar",
    "Equal weights": "Eşit ağırlık",
    "Load": "Yükle",
    "Currency": "Para birimi",
    "Currency: automatic": "Para birimi: otomatik",
    "Convert to TRY": "TRY’ye çevir",
    "Convert to USD": "USD’ye çevir",
    "Convert to EUR": "EUR’ye çevir",
    "Convert to GBP": "GBP’ye çevir",
    "Convert to JPY": "JPY’ye çevir",
    "Convert to CHF": "CHF’ye çevir",
    "History": "Geçmiş",
    "Last year": "Son 1 yıl",
    "Last 3 years": "Son 3 yıl",
    "Last 5 years": "Son 5 yıl",
    "Last 10 years": "Son 10 yıl",
    "All available": "Tümü",
    "Sample scenario": "Örnek senaryo",
    "Or upload a CSV": "Ya da bir CSV yükle",
    "Estimation method": "Tahmin yöntemi",
    "Historical": "Tarihsel",
    "Parametric (normal)": "Parametrik (normal)",
    "Cornish-Fisher": "Cornish-Fisher",
    "Rolling window (periods)": "Kayan pencere (dönem)",
    "Saved analyses": "Kayıtlı analizler",
    "Nothing saved yet. Run an analysis and give it a name to keep it here.": "Henüz kayıt yok. Bir analiz çalıştırıp ona bir ad verirsen burada saklanır.",
    "Compare selected": "Seçilenleri karşılaştır",
    "Tick two to four analyses to compare them side by side.": "Yan yana karşılaştırmak için iki ila dört analiz işaretle.",
    "Saved analyses side by side": "Kayıtlı analizler yan yana",
    "Close": "Kapat",
    "Name for this analysis": "Bu analizin adı",
    "Save": "Kaydet",
    "Download report": "Raporu indir",
    "Download series (CSV)": "Seriyi indir (CSV)",
    "Risk at a glance": "Bir bakışta risk",
    "Where the risk comes from": "Risk nereden geliyor",
    "Correlation of returns": "Getirilerin korelasyonu",
    "Stress: the worst stretches in the data": "Stres: verideki en kötü dönemler",
    "Model validation": "Model doğrulaması",
    "Growth of 100 and drawdown": "100’ün büyümesi ve düşüş",
    "Daily return against the VaR forecast": "Günlük getiri ve VaR tahmini",
    "Distribution of returns": "Getirilerin dağılımı",
    "Tail shape: QQ plot against the normal": "Kuyruk şekli: normale karşı QQ grafiği",
    "Definitions and assumptions": "Tanımlar ve varsayımlar",
    "Value at risk (VaR)": "Riske maruz değer (VaR)",
    "The one period return that is not expected to be breached at the chosen confidence level. Losses are negative.": "Seçilen güven düzeyinde aşılması beklenmeyen tek dönemlik getiri. Kayıplar negatiftir.",
    "Expected shortfall (ES)": "Beklenen kayıp (ES)",
    "The average return on the periods that breach the VaR. Never better than the VaR.": "VaR’ın aşıldığı dönemlerdeki ortalama getiri. VaR’dan hiçbir zaman daha iyi olmaz.",
    "Breach": "İhlal",
    "before": "önce",
    "Kupiec test": "Kupiec testi",
    "number": "sayısını",
    "Christoffersen independence test": "Christoffersen bağımsızlık testi",
    "Tests whether a breach makes another more likely the next period, i.e. whether they cluster.": "Bir ihlalin ertesi dönemde başka bir ihlali daha olası kılıp kılmadığını, yani ihlallerin kümelenip kümelenmediğini sınar.",
    "Conditional coverage": "Koşullu kapsama",
    "Kupiec and independence combined.": "Kupiec ve bağımsızlık testlerinin birleşimi.",
    "Basel traffic light": "Basel trafik ışığı",
    "Green, yellow or red from the binomial probability of seeing this many breaches or fewer if the model were right (95% and 99.99% cut-offs).": "Model doğru olsaydı bu kadar ya da daha az ihlal görme olasılığından (binom) çıkan yeşil, sarı ya da kırmızı (%95 ve %99,99 eşikleri).",
    "Stress window": "Stres penceresi",
    "The worst compounded return over any 1, 5 or 20 consecutive periods in the data, with its dates. It is what actually happened, not a forecast.": "Verideki ardışık 1, 5 ya da 20 dönemin en kötü bileşik getirisi ve tarihleri. Bu bir tahmin değil, gerçekten yaşananlardır.",
    "Share of volatility": "Volatilite payı",
    "Each asset's weight times its covariance with the portfolio, as a fraction of the portfolio variance. The shares add up to 100%.": "Her varlığın ağırlığı ile portföyle kovaryansının çarpımı, portföy varyansının oranı olarak. Paylar toplamda %100 eder.",
    "Share of expected shortfall": "Beklenen kayıp payı",
    "The weight times the asset's average return on the periods when the portfolio was in its tail (worse than its VaR). Adds up to 100%.": "Ağırlık çarpı, portföyün kuyruğunda (VaR’ından kötü) olduğu dönemlerde varlığın ortalama getirisi. Toplamı %100’dür.",
    "Diversification ratio": "Çeşitlendirme oranı",
    "The weighted average volatility of the assets divided by the volatility of the portfolio. 1 means no diversification.": "Varlıkların ağırlıklı ortalama volatilitesinin portföyün volatilitesine oranı. 1, çeşitlendirme olmadığı anlamına gelir.",
    "QQ plot": "QQ grafiği",
    "Sample quantiles, in standard deviations, against normal quantiles. Points on the dashed line mean normal tails; points below it in the left tail mean fatter losses than a normal distribution allows.": "Örnek kantilleri (standart sapma cinsinden) ve normal kantiller. Kesikli çizgi üzerindeki noktalar normal kuyruk demektir; sol kuyrukta çizginin altındaki noktalar, normal dağılımın izin verdiğinden daha kalın kayıp kuyruğuna işaret eder.",
    "Risk analytics application.": "Risk analizi uygulaması.",
    "Built on": "Altyapı:",
    "Sample data is simulated (GARCH(1,1) with Student-t innovations). Not investment advice.": "Örnek veriler simüle edilmiştir (Student-t şoklu GARCH(1,1)). Yatırım tavsiyesi değildir.",
    "Value at risk, expected shortfall and model validation for a return series or a portfolio, computed by": "Bir getiri serisi ya da portföy için riske maruz değer, beklenen kayıp ve model doğrulaması; şu modülle hesaplanır:",
    ".": ".",
    "A header row with the asset names, then": "Varlık adlarının yazılı olduğu bir başlık satırı, ardından",
    "or just": "ya da yalnızca",
    ". Two to": ". Satır sayısı aynı olan 2 ile",
    "assets with the same number of rows.": "arası varlık.",
    "One value per line, or": "Her satıra bir değer ya da",
    ". Up to 5,000 rows. Returns are simple returns as fractions or percentages (": ". En fazla 5.000 satır. Getiriler; kesir ya da yüzde olarak basit getirilerdir (",
    "or": "ya da",
    ").": ").",
    "Confidence level:": "Güven düzeyi:",
    "Returns": "Getiriler",
    "Prices": "Fiyatlar",
    "Value at risk, expected shortfall and VaR backtesting, built on gs_quant.timeseries.risk_metrics": "Riske maruz değer, beklenen kayıp ve VaR geriye dönük testi; gs_quant.timeseries.risk_metrics üzerine kurulu",
    "What the uploaded values are": "Yüklenen değerlerin türü",
    "Comparison": "Karşılaştırma",
    "Name this analysis": "Bu analize ad ver",
    "Risk by asset": "Varlık bazında risk",
    "Correlation matrix": "Korelasyon matrisi",
    "Worst windows": "En kötü pencereler",
    "Backtest results": "Geriye dönük test sonuçları",
    "The empirical quantile of the window. No distribution assumed; noisy in the far tail.": "Penceredeki deneysel kantil. Dağılım varsayılmaz; uzak kuyrukta gürültülüdür.",
    "A normal distribution fitted to the window. Smooth, but understates fat tails.": "Pencereye uydurulan normal dağılım. Pürüzsüzdür ama kalın kuyrukları olduğundan küçük gösterir.",
    "A normal quantile corrected for skewness and kurtosis. Suits moderately fat tails.": "Çarpıklık ve basıklık için düzeltilmiş normal kantil. Orta kalınlıktaki kuyruklara uygundur.",
    "historical": "tarihsel",
    "parametric": "parametrik",
    "Could not reach the server. Is it still running?": "Sunucuya ulaşılamadı. Hâlâ çalışıyor mu?",
    "A valid access token is required.": "Geçerli bir erişim anahtarı gerekli.",
    "The server answered with status {status}": "Sunucu {status} durumuyla yanıt verdi",
    "{n} breaches in {periods} periods against {expected} expected": "{periods} dönemde {n} ihlal ({expected} bekleniyordu)",
    "{count}: the model understates risk (Kupiec p {p}).": "{count}: model riski olduğundan küçük gösteriyor (Kupiec p {p}).",
    "{count}: the model overstates risk (Kupiec p {p}).": "{count}: model riski olduğundan büyük gösteriyor (Kupiec p {p}).",
    "{count}: consistent with the confidence level (Kupiec p {p}).": "{count}: güven düzeyiyle uyumlu (Kupiec p {p}).",
    "Breaches cluster: the chance of one the day after a breach is {after}, against {otherwise} otherwise.": "İhlaller kümeleniyor: bir ihlalden sonraki gün yeni bir ihlal olasılığı {after}; diğer günlerde {otherwise}.",
    "No evidence that breaches cluster in time.": "İhlallerin zamanda kümelendiğine dair kanıt yok.",
    "Basel traffic light: {zone}.": "Basel trafik ışığı: {zone}.",
    "Annualized return": "Yıllıklandırılmış getiri",
    "compound": "bileşik",
    "Annualized volatility": "Yıllıklandırılmış volatilite",
    "{n} periods per year": "yılda {n} dönem",
    "{conf} value at risk": "{conf} riske maruz değer",
    "one period, {method}": "tek dönem, {method}",
    "{conf} expected shortfall": "{conf} beklenen kayıp",
    "average return on breach periods": "ihlal dönemlerindeki ortalama getiri",
    "Drawdown and risk-adjusted return": "Düşüş ve riske göre düzeltilmiş getiri",
    "Maximum drawdown": "Maksimum düşüş",
    "Worst period": "En kötü dönem",
    "Sortino ratio": "Sortino oranı",
    "Calmar ratio": "Calmar oranı",
    "Ulcer index": "Ulcer endeksi",
    "Shape of the distribution": "Dağılımın şekli",
    "Skewness": "Çarpıklık",
    "Excess kurtosis (0 = normal)": "Fazla basıklık (0 = normal)",
    "Best period": "En iyi dönem",
    "Downside deviation (annualized)": "Aşağı yönlü sapma (yıllıklandırılmış)",
    "Omega ratio": "Omega oranı",
    "✕ Rejected": "✕ Reddedildi",
    "✓ Not rejected": "✓ Reddedilmedi",
    "Number of breaches against the confidence level": "İhlal sayısı ve güven düzeyi",
    "Christoffersen independence": "Christoffersen bağımsızlık",
    "Do breaches cluster? ({n} of {total} breaches were followed by another)": "İhlaller kümeleniyor mu? ({total} ihlalin {n} tanesinin ardından bir ihlal daha geldi)",
    "Number and timing of breaches together": "İhlallerin sayısı ve zamanlaması birlikte",
    "{n} breaches against {expected} expected": "{n} ihlal ({expected} bekleniyordu)",
    "Test": "Test",
    "Statistic": "İstatistik",
    "p-value": "p-değeri",
    "Result": "Sonuç",
    "Saved report": "Kayıtlı rapor",
    "Market data": "Piyasa verisi",
    "Simulated data": "Simüle veri",
    "Your data": "Senin verin",
    "{from} to {to}": "{from} – {to}",
    "{n} observations": "{n} gözlem",
    "{n} assets": "{n} varlık",
    "Uploaded series": "Yüklenen seri",
    "{title} scenario": "{title} senaryosu",
    "Uploaded portfolio": "Yüklenen portföy",
    "{n} returns": "{n} getiri",
    "saved {date}": "{date} tarihinde kaydedildi",
    "prices from {source}": "fiyatlar: {source}",
    "Rolling window of {window} periods, {n} periods per year.": "{window} dönemlik kayan pencere, yılda {n} dönem.",
    "Every figure is a fraction of the portfolio, and losses are negative.": "Her rakam portföyün bir oranıdır ve kayıplar negatiftir.",
    "Diversification ratio **{ratio}**: the portfolio is {less} less volatile than the weighted average of its assets.": "Çeşitlendirme oranı **{ratio}**: portföy, varlıklarının ağırlıklı ortalamasından {less} daha az oynak.",
    "**{name}** is {weight} of the portfolio but {loss} of the loss on the {n} worst periods (the {conf} tail).": "**{name}** portföyün {weight} kadarı ama en kötü {n} dönemdeki ({conf} kuyruğu) kaybın {loss} kadarı.",
    "Tail losses are spread roughly in line with the weights ({n} periods in the {conf} tail).": "Kuyruk kayıpları yaklaşık olarak ağırlıklarla uyumlu dağılmış ({conf} kuyruğunda {n} dönem).",
    "Asset": "Varlık",
    "Weight": "Ağırlık",
    "Volatility": "Volatilite",
    "{conf} VaR alone": "Tek başına {conf} VaR",
    "Portfolio": "Portföy",
    "The worst single period lost **{loss}** on {date}, {times} times the {conf} VaR.": "En kötü tek dönem {date} tarihinde **{loss}** kaybettirdi; bu, {conf} VaR’ın {times} katı.",
    "The worst {n} periods in a row lost **{loss}** ({from} to {to}).": "Üst üste en kötü {n} dönem **{loss}** kaybettirdi ({from} – {to}).",
    "Window": "Pencere",
    "Return": "Getiri",
    "From": "Başlangıç",
    "To": "Bitiş",
    "Worst {n} periods": "En kötü {n} dönem",
    "Growth of 100 invested, ending at {end}. Maximum drawdown {depth}, from {from} to {to}.": "Yatırılan 100’ün büyümesi, {end} ile bitiyor. Maksimum düşüş {depth}, {from} ile {to} arasında.",
    "Ends at **{end}**. Deepest fall **{depth}** from the peak on {from} to the trough on {to}.": "**{end}** ile biter. En derin düşüş **{depth}**: {from} tarihindeki zirveden {to} tarihindeki dibe.",
    "Growth of 100": "100’ün büyümesi",
    "Max drawdown {depth}": "Maks. düşüş {depth}",
    "Drawdown": "Düşüş",
    "Daily returns against the {conf} value at risk forecast: {n} breaches in {periods} periods, {expected} expected.": "Günlük getiriler ve {conf} riske maruz değer tahmini: {periods} dönemde {n} ihlal, {expected} bekleniyordu.",
    "The forecast was breached **{n} times** in {periods} periods ({expected} expected at {conf}). Each return is judged against the forecast made the period before.": "Tahmin {periods} dönemde **{n} kez** aşıldı ({conf} düzeyinde {expected} bekleniyordu). Her getiri, bir önceki dönemde yapılan tahminle karşılaştırılır.",
    "{conf} VaR": "{conf} VaR",
    "Expected shortfall": "Beklenen kayıp",
    "Daily return": "Günlük getiri",
    "VaR forecast": "VaR tahmini",
    "Histogram of returns with the normal curve, value at risk {var} and expected shortfall {es}.": "Getirilerin histogramı, normal eğri, riske maruz değer {var} ve beklenen kayıp {es}.",
    "({n} outliers not shown)": "({n} aykırı değer gösterilmiyor)",
    "Central 99% of returns.{outliers} VaR **{var}**, expected shortfall **{es}** at {conf}.": "Getirilerin ortadaki %99’u.{outliers} {conf} düzeyinde VaR **{var}**, beklenen kayıp **{es}**.",
    "Days": "Gün",
    "Normal fit": "Normal uyum",
    "QQ plot of standardised returns against normal quantiles. The worst return is {worst} standard deviations; a normal sample of this size would reach about {normal}.": "Standartlaştırılmış getirilerin normal kantillere karşı QQ grafiği. En kötü getiri {worst} standart sapma; bu büyüklükte normal bir örnek yaklaşık {normal} değerine ulaşırdı.",
    "Worst return is **{worst}σ**; a normal sample this size would reach about {normal}σ.": "En kötü getiri **{worst}σ**; bu büyüklükte normal bir örnek yaklaşık {normal}σ’ya ulaşırdı.",
    "The left tail is fatter than a normal distribution allows.": "Sol kuyruk, normal dağılımın izin verdiğinden daha kalın.",
    "The left tail is in line with a normal distribution.": "Sol kuyruk normal dağılımla uyumlu.",
    "Normal quantile (standard deviations)": "Normal kantil (standart sapma)",
    "Sample quantile": "Örnek kantili",
    "Beyond the {conf} VaR level": "{conf} VaR düzeyinin ötesi",
    "The file is empty.": "Dosya boş.",
    "The file has no data rows.": "Dosyada veri satırı yok.",
    "The file has {n} rows, the maximum is {max}.": "Dosyada {n} satır var, en fazla {max} olabilir.",
    "Row {row} does not contain a number.": "{row}. satırda sayı yok.",
    "Row {row}: the first column must be a date such as 2024-03-29.": "{row}. satır: ilk sütun 2024-03-29 gibi bir tarih olmalı.",
    "A portfolio needs at least two asset columns.": "Portföy için en az iki varlık sütunu gerekir.",
    "The file has {n} assets, the maximum is {max}.": "Dosyada {n} varlık var, en fazla {max} olabilir.",
    "Asset {n}": "Varlık {n}",
    "The asset name \"{name}\" appears twice.": "\"{name}\" varlık adı iki kez geçiyor.",
    "Row {row} has {n} columns, expected {expected}.": "{row}. satırda {n} sütun var, {expected} bekleniyordu.",
    "Row {row}, {name}: not a number.": "{row}. satır, {name}: sayı değil.",
    "That access token was not accepted.": "Bu erişim anahtarı kabul edilmedi.",
    "Enter the access token to continue.": "Devam etmek için erişim anahtarını gir.",
    "Calculating…": "Hesaplanıyor…",
    "Loading sample data…": "Örnek veri yükleniyor…",
    "Every weight must be a number.": "Her ağırlık bir sayı olmalı.",
    "The weights sum to 100%.": "Ağırlıkların toplamı %100.",
    "The weights sum to {total} and are scaled to 100%.": "Ağırlıkların toplamı {total}; %100’e ölçeklenir.",
    "The weights sum to {total}.": "Ağırlıkların toplamı {total}.",
    "Loading sample portfolio…": "Örnek portföy yükleniyor…",
    "Sample portfolio": "Örnek portföy",
    "Assets held at constant weights, rebalanced every period. Shows what each asset adds to the risk.": "Varlıklar sabit ağırlıkta tutulur, her dönem yeniden dengelenir. Her varlığın riske ne kattığını gösterir.",
    "One series of returns or prices.": "Tek bir getiri ya da fiyat serisi.",
    "Upload a CSV of several assets or load the sample portfolio.": "Birden çok varlığın CSV dosyasını yükle ya da örnek portföyü yükle.",
    "Load several symbols": "Birden çok sembol yükle",
    "Load by symbol": "Sembolle yükle",
    "Daily closing prices from {source}, adjusted for splits and dividends, two to {max} symbols separated by commas. They can be delayed, and are not investment advice.": "{source} kaynağından günlük kapanış fiyatları (bölünme ve temettüye göre düzeltilmiş), virgülle ayrılmış 2 ile {max} arası sembol. Gecikmeli olabilir, yatırım tavsiyesi değildir.",
    "Daily closing prices from {source}, two to {max} symbols separated by commas. They can be delayed, and are not investment advice.": "{source} kaynağından günlük kapanış fiyatları, virgülle ayrılmış 2 ile {max} arası sembol. Gecikmeli olabilir, yatırım tavsiyesi değildir.",
    "Daily closing prices from {source}, adjusted for splits and dividends. They can be delayed, and are not investment advice.": "{source} kaynağından günlük kapanış fiyatları (bölünme ve temettüye göre düzeltilmiş). Gecikmeli olabilir, yatırım tavsiyesi değildir.",
    "Daily closing prices from {source}. They can be delayed, and are not investment advice.": "{source} kaynağından günlük kapanış fiyatları. Gecikmeli olabilir, yatırım tavsiyesi değildir.",
    "Give at least two symbols, separated by commas.": "Virgülle ayırarak en az iki sembol gir.",
    "Give one symbol, or switch to a portfolio for several.": "Tek bir sembol gir; birden çoğu için portföye geç.",
    "Loading prices from {source}…": "{source} kaynağından fiyatlar yükleniyor…",
    "in {currency}": "{currency} cinsinden",
    "Series": "Seri",
    "{conf} VaR {var}": "{conf} VaR {var}",
    "Basel {zone}": "Basel {zone}",
    "Open": "Aç",
    "Open {name}": "{name} analizini aç",
    "Report": "Rapor",
    "Download the report of {name}": "{name} raporunu indir",
    "Delete": "Sil",
    "Delete {name}": "{name} analizini sil",
    "Compare {name}": "{name} analizini karşılaştır",
    "Compare at most four at a time.": "Aynı anda en fazla dört analiz karşılaştırılır.",
    "{n} selected.": "{n} seçildi.",
    "Comparing…": "Karşılaştırılıyor…",
    "Opening…": "Açılıyor…",
    "Saving…": "Kaydediliyor…",
    "Saved as “{name}”.": "“{name}” adıyla kaydedildi.",
    "Delete “{name}”?": "“{name}” silinsin mi?",
    "What if? Shocks of your own": "Ya şöyle olursa? Kendi şoklarını gir",
    "Enter how much each asset would move at once, in percent (-10 is a fall of 10%). The effect on the portfolio is the weighted sum, compared with the VaR and the expected shortfall.": "Her varlığın bir anda ne kadar hareket edeceğini yüzde olarak gir (-10, %10 düşüş demektir). Portföye etkisi ağırlıklı toplamdır; VaR ve beklenen kayıpla karşılaştırılır.",
    "What-if scenarios": "Ya şöyle olursa senaryoları",
    "Add a scenario": "Senaryo ekle",
    "Scenario": "Senaryo",
    "{asset} (%)": "{asset} (%)",
    "Effect": "Etki",
    "× VaR": "× VaR",
    "× ES": "× ES",
    "Scenario name": "Senaryo adı",
    "Shock of {asset} (%)": "{asset} şoku (%)",
    "Remove": "Kaldır",
    "Remove {name}": "{name} senaryosunu kaldır",
    "Scenario {n}": "Senaryo {n}",
    "At most five scenarios.": "En fazla beş senaryo olabilir.",
    "My portfolios": "Portföylerim",
    "Name for this portfolio": "Bu portföyün adı",
    "Name this portfolio": "Bu portföye ad ver",
    "Save portfolio": "Portföyü kaydet",
    "No portfolios yet.": "Henüz portföy yok.",
    "Saves the symbols, the weights, the currency and the history. Opening one loads fresh prices.": "Sembolleri, ağırlıkları, para birimini ve geçmişi kaydeder. Bir portföyü açınca güncel fiyatlar yüklenir.",
    "Load prices by symbol above, set the weights, and the portfolio can be saved here.": "Yukarıdan sembolle fiyat yükle, ağırlıkları ayarla; portföy burada kaydedilebilir.",
    "Load {name}": "{name} portföyünü yükle",
    "Portfolio “{name}” saved.": "“{name}” portföyü kaydedildi.",
    "Convert to {currency}": "{currency}’ye çevir",
    "Green": "Yeşil",
    "Yellow": "Sarı",
    "Red": "Kırmızı",
    "Type": "Tür",
    "Saved": "Kaydedildi",
    "Confidence": "Güven düzeyi",
    "Method": "Yöntem",
    "Observations": "Gözlem",
    "Value at risk": "Riske maruz değer",
    "Breaches (expected)": "İhlal (beklenen)",
    "Kupiec p-value": "Kupiec p-değeri",
    "Calm market": "Sakin piyasa",
    "Volatile market": "Oynak piyasa",
    "Regime shift": "Rejim değişimi",
    "Low volatility, close to normally distributed returns": "Düşük volatilite, normale yakın dağılan getiriler",
    "Volatility clustering and fat tails, as in equity index returns": "Hisse endeksi getirilerinde olduğu gibi volatilite kümelenmesi ve kalın kuyruklar",
    "A calm market that turns turbulent, so a trailing VaR model lags the change": "Sakin bir piyasa çalkantılı hale gelir; geriye dönük pencereli bir VaR modeli değişimi geç fark eder"
  };

  // Turkish for the messages the server sends. Each entry is [regular expression, template with $1, $2 ... for the groups].
  const SERVER_PATTERNS = [
    [
      "^At most (\\d+) observations are supported, got (\\d+)$",
      "En fazla $1 gözlem desteklenir, $2 gözlem verildi"
    ],
    [
      "^Values must be finite numbers$",
      "Değerler sonlu sayılar olmalı"
    ],
    [
      "^Got (\\d+) dates for (\\d+) values$",
      "$2 değer için $1 tarih verildi"
    ],
    [
      "^Dates must be strictly increasing, without duplicates$",
      "Tarihler tekrarsız ve kesinlikle artan olmalı"
    ],
    [
      "^Prices must be positive$",
      "Fiyatlar pozitif olmalı"
    ],
    [
      "^Simple returns must be greater than -100%$",
      "Basit getiriler %-100’den büyük olmalı"
    ],
    [
      "^At least 60 returns are needed for a meaningful analysis$",
      "Anlamlı bir analiz için en az 60 getiri gerekir"
    ],
    [
      "^The rolling window \\((\\d+)\\) must be shorter than the series \\((\\d+) returns\\)$",
      "Kayan pencere ($1) seriden ($2 getiri) kısa olmalı"
    ],
    [
      "^No dates were given, so (\\d+) periods per year are assumed$",
      "Tarih verilmediği için yılda $1 dönem varsayıldı"
    ],
    [
      "^Returns were calculated as simple returns from the prices$",
      "Getiriler fiyatlardan basit getiri olarak hesaplandı"
    ],
    [
      "^Expected shortfall uses the parametric method, as Cornish-Fisher is not defined for it$",
      "Cornish-Fisher beklenen kayıp için tanımlı olmadığından beklenen kayıp parametrik yöntemle hesaplandı"
    ],
    [
      "^A portfolio needs between (\\d+) and (\\d+) assets, got (\\d+)$",
      "Portföy için $1 ile $2 arası varlık gerekir, $3 varlık verildi"
    ],
    [
      "^Asset names must be 1 to (\\d+) characters$",
      "Varlık adları 1 ile $1 karakter arasında olmalı"
    ],
    [
      "^Asset names must be unique$",
      "Varlık adları benzersiz olmalı"
    ],
    [
      "^Every asset needs the same number of observations$",
      "Her varlığın gözlem sayısı aynı olmalı"
    ],
    [
      "^Weights must be given for exactly the assets, no more and no fewer$",
      "Ağırlıklar tam olarak varlıklar için verilmeli, ne fazla ne eksik"
    ],
    [
      "^Weights must be finite numbers$",
      "Ağırlıklar sonlu sayılar olmalı"
    ],
    [
      "^Weights must sum to a positive number$",
      "Ağırlıkların toplamı pozitif olmalı"
    ],
    [
      "^Equal weights \\(([\\d.]+)% each\\) were assumed$",
      "Eşit ağırlık (her biri %$1) varsayıldı"
    ],
    [
      "^Weights summed to (\\S+) and were scaled to sum to 1$",
      "Ağırlıkların toplamı $1 çıktı ve toplamı 1 olacak şekilde ölçeklendi"
    ],
    [
      "^The portfolio is rebalanced to its weights every period$",
      "Portföy her dönem ağırlıklarına yeniden dengelenir"
    ],
    [
      "^The portfolio has no variance, so its risk cannot be decomposed$",
      "Portföyün varyansı yok, bu yüzden riski ayrıştırılamaz"
    ],
    [
      "^The portfolio lost more than 100% in a period, which the analysis cannot handle$",
      "Portföy bir dönemde %100’den fazla kaybetti; analiz bunu işleyemez"
    ],
    [
      "^Request body is larger than (\\d+) bytes$",
      "İstek gövdesi $1 bayttan büyük"
    ],
    [
      "^There is no such run$",
      "Böyle bir kayıtlı analiz yok"
    ],
    [
      "^Loading prices by symbol is not enabled on this server$",
      "Bu sunucuda sembolle fiyat yükleme açık değil"
    ],
    [
      "^A valid access token is required$",
      "Geçerli bir erişim anahtarı gerekli"
    ],
    [
      "^Something went wrong on the server$",
      "Sunucuda bir şeyler ters gitti"
    ],
    [
      "^The run store is not available$",
      "Kayıt deposuna ulaşılamıyor"
    ],
    [
      "^Choose between (\\d+) and (\\d+) different saved analyses to compare$",
      "Karşılaştırmak için $1 ile $2 arası farklı kayıtlı analiz seç"
    ],
    [
      "^The saved run \\\"(.*)\\\" can no longer be analysed: (.*)$",
      "“$1” kaydı artık analiz edilemiyor: $2"
    ],
    [
      "^Scenario \\\"(.*)\\\": unknown asset \\\"(.*)\\\"$",
      "“$1” senaryosunda bilinmeyen varlık: “$2”"
    ],
    [
      "^You can keep at most (\\d+) portfolios: delete one first$",
      "En fazla $1 portföy saklayabilirsin: önce birini sil"
    ],
    [
      "^There is no such portfolio$",
      "Böyle bir portföy yok"
    ],
    [
      "^Too many requests: try again in (\\d+) seconds$",
      "Çok fazla istek: $1 saniye sonra yeniden dene"
    ],
    [
      "^Too many failed attempts: try again in (\\d+) seconds$",
      "Çok fazla başarısız deneme: $1 saniye sonra yeniden dene"
    ],
    [
      "^(Stooq|Yahoo Finance) does not know this symbol$",
      "$1 bu sembolü tanımıyor"
    ],
    [
      "^(Stooq|Yahoo Finance) answered with status (\\d+)$",
      "$1 $2 durumuyla yanıt verdi"
    ],
    [
      "^(Stooq|Yahoo Finance) sent more data than expected$",
      "$1 beklenenden fazla veri gönderdi"
    ],
    [
      "^(Stooq|Yahoo Finance) did not answer in time$",
      "$1 zamanında yanıt vermedi"
    ],
    [
      "^Could not reach (Stooq|Yahoo Finance)$",
      "$1 kaynağına ulaşılamadı"
    ],
    [
      "^(Stooq|Yahoo Finance) has no prices for this symbol$",
      "$1 bu sembol için fiyat bulamadı"
    ],
    [
      "^Stooq did not answer with prices \\(it may now ask for an API key\\)$",
      "Stooq fiyat göndermedi (artık API anahtarı istiyor olabilir)"
    ],
    [
      "^(Stooq|Yahoo Finance) answered in a format that was not understood$",
      "$1 anlaşılamayan bir biçimde yanıt verdi"
    ],
    [
      "^(Stooq|Yahoo Finance) is limiting requests: try again in a minute$",
      "$1 istekleri sınırlıyor: bir dakika sonra yeniden dene"
    ],
    [
      "^Give between (\\d+) and (\\d+) symbols, separated by commas$",
      "Virgülle ayırarak $1 ile $2 arası sembol gir"
    ],
    [
      "^\\\"(.*)\\\" is not a valid symbol \\(.*\\)$",
      "“$1” geçerli bir sembol değil (yalnızca harf, rakam ve . ^ _ = - kullanılabilir)"
    ],
    [
      "^Each symbol can be given once$",
      "Her sembol yalnızca bir kez girilebilir"
    ],
    [
      "^Only (\\d+) dates have prices for all of (.*); at least (\\d+) are needed$",
      "$2 sembollerinin hepsi için yalnızca $1 tarihte fiyat var; en az $3 gerekir"
    ],
    [
      "^\\\"(.*)\\\" is not a currency code such as USD or TRY$",
      "“$1” USD ya da TRY gibi bir para birimi kodu değil"
    ],
    [
      "^Converting to another currency needs Yahoo Finance, not (.*)$",
      "Başka bir para birimine çevirme için Yahoo Finance gerekir, $1 yetmez"
    ],
    [
      "^No exchange rate between (\\w+) and (\\w+) is available$",
      "$1 ile $2 arasında döviz kuru bulunamadı"
    ],
    [
      "^The (\\w+)/(\\w+) exchange rate does not cover the dates of these prices$",
      "$1/$2 döviz kuru bu fiyatların tarihlerini kapsamıyor"
    ],
    [
      "^The assets are quoted in different currencies, so prices were converted to (\\w+)$",
      "Varlıklar farklı para birimlerinde işlem gördüğünden fiyatlar $1 para birimine çevrildi"
    ],
    [
      "^Prices are in (\\w+), converted at the daily rate of (.*)$",
      "Fiyatlar $1 cinsinden, günlük $2 kuruyla çevrildi"
    ],
    [
      "^Prices are in (\\w+)$",
      "Fiyatlar $1 cinsinden"
    ]
  ].map(([source, template]) => [new RegExp(source), template]);

  const preferred = () => (String(navigator.language || '').toLowerCase().startsWith('tr') ? 'tr' : 'en');
  let lang = preferred();
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (LANGUAGES.includes(saved)) lang = saved;
  } catch (error) {
    /* storage can be unavailable (private windows): the browser's language is used */
  }

  function fill(text, vars) {
    return vars ? text.replace(/\{(\w+)\}/g, (match, name) => (name in vars ? String(vars[name]) : match)) : text;
  }

  function t(text, vars) {
    const translated = lang === 'tr' && Object.prototype.hasOwnProperty.call(TR, text) ? TR[text] : text;
    return fill(translated, vars);
  }

  // A message that came from the server, in the current language where it is known
  function server(message) {
    if (lang !== 'tr' || typeof message !== 'string') return message;
    for (const [pattern, template] of SERVER_PATTERNS) {
      const match = pattern.exec(message);
      if (match) return template.replace(/\$(\d)/g, (found, i) => (match[Number(i)] === undefined ? found : match[Number(i)]));
    }
    return message;
  }

  const clean = (text) => text.replace(/\s+/g, ' ').trim();
  const originals = new WeakMap(); // the English text of every node that was translated

  // Text that sits in the page itself: data-t (the element's own text), data-t-nodes (its text nodes, around child
  // elements such as <code>) and data-t-attr (attributes such as aria-label)
  function applyDocument(root = document) {
    for (const element of root.querySelectorAll('[data-t]')) {
      if (!originals.has(element)) originals.set(element, clean(element.textContent));
      element.textContent = t(originals.get(element));
    }
    for (const element of root.querySelectorAll('[data-t-nodes]')) {
      for (const node of element.childNodes) {
        if (node.nodeType !== Node.TEXT_NODE) continue;
        if (!originals.has(node)) originals.set(node, node.nodeValue);
        const original = originals.get(node);
        if (!clean(original)) continue;
        const lead = original.match(/^\s*/)[0];
        const trail = original.match(/\s*$/)[0];
        node.nodeValue = lead + t(clean(original)) + trail;
      }
    }
    for (const element of root.querySelectorAll('[data-t-attr]')) {
      for (const name of element.dataset.tAttr.split(',')) {
        const key = `data-en-${name}`;
        if (!element.hasAttribute(key)) element.setAttribute(key, element.getAttribute(name) || '');
        element.setAttribute(name, t(element.getAttribute(key)));
      }
    }
    const title = document.querySelector('title');
    if (root === document && title) document.title = title.textContent;
  }

  function setLang(next) {
    if (!LANGUAGES.includes(next)) return;
    lang = next;
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch (error) {
      /* storage can be unavailable: the choice then lasts until the page is closed */
    }
  }

  window.I18n = {
    t,
    server,
    applyDocument,
    setLang,
    translations: TR,
    get lang() {
      return lang;
    },
  };
})();
