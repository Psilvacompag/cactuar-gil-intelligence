(function initializeConversionAdvisor(root) {
  function finite(value) {
    const number = Number(value);
    return value === null || value === undefined || value === "" || !Number.isFinite(number)
      ? null
      : number;
  }

  function conversionKey(item) {
    return [
      item.currencyItemId,
      item.currencyQuantity,
      item.rewardItemId,
      item.rewardQuantity,
      item.rewardIsHq ? 1 : 0,
    ].join(":");
  }

  function pressureFactor(item) {
    const pressure = String(item.listingDepth?.pressure || "").toUpperCase();
    if (pressure === "HIGH") return 0.78;
    if (pressure === "MEDIUM") return 0.9;
    return 1;
  }

  function eligible(item) {
    return item.status === "FRESH"
      && !item.isMultiCost
      && finite(item.currencyQuantity) > 0
      && finite(item.netGilPerCurrency) > 0
      && finite(item.netGilPerExchange) > 0
      && finite(item.marketUnitPrice) > 0;
  }

  function analyzeCurrency(items) {
    const candidates = items.filter(eligible);
    if (!candidates.length) return null;
    const maximumReturn = Math.max(...candidates.map((item) => finite(item.netGilPerCurrency)));
    const observedVelocities = candidates
      .map((item) => finite(item.dailySaleVelocity))
      .filter((value) => value !== null && value > 0);
    const maximumVelocity = observedVelocities.length ? Math.max(...observedVelocities) : 0;

    const ranked = candidates.map((item) => {
      const netReturn = finite(item.netGilPerCurrency);
      const saleVelocity = finite(item.dailySaleVelocity);
      const returnScore = Math.log1p(netReturn) / Math.log1p(maximumReturn);
      const liquidityScore = saleVelocity === null || maximumVelocity <= 0
        ? 0
        : Math.log1p(Math.max(0, saleVelocity)) / Math.log1p(maximumVelocity);
      const confidenceScore = saleVelocity === null ? 0.25 : 0.85;
      const score = Math.round(
        100 * (returnScore * 0.55 + liquidityScore * 0.35 + confidenceScore * 0.1)
          * pressureFactor(item),
      );
      return { item, score, returnScore, liquidityScore, saleVelocity, role: null };
    }).sort((a, b) => b.score - a.score || b.item.netGilPerCurrency - a.item.netGilPerCurrency);

    const best = ranked[0];
    const returnLeader = [...ranked].sort((a, b) =>
      b.item.netGilPerCurrency - a.item.netGilPerCurrency || b.score - a.score)[0];
    const liquidityLeader = [...ranked]
      .filter((candidate) =>
        candidate !== best
        && candidate !== returnLeader
        && candidate.saleVelocity !== null
        && candidate.item.netGilPerCurrency >= maximumReturn * 0.15)
      .sort((a, b) => b.saleVelocity - a.saleVelocity || b.score - a.score)[0] || null;

    const unverified = !ranked.some((candidate) => candidate.saleVelocity !== null);
    best.role = unverified ? "SPECULATIVE" : "BEST";
    if (returnLeader !== best) returnLeader.role = "RETURN";
    if (liquidityLeader) liquidityLeader.role = "LIQUID";
    ranked.forEach((candidate) => {
      if (!candidate.role && candidate.saleVelocity === null && candidate.returnScore >= 0.8) {
        candidate.role = "SPECULATIVE";
      }
    });

    return { ranked, best, returnLeader, liquidityLeader, unverified };
  }

  function selectForBudget(advice, budget) {
    if (!advice) return null;
    const available = Math.max(0, Math.floor(finite(budget) || 0));
    const ranked = advice.ranked.filter((candidate) => candidate.item.currencyQuantity <= available);
    if (!ranked.length) return null;
    const best = ranked[0];
    const returnLeader = [...ranked].sort((a, b) =>
      b.item.netGilPerCurrency - a.item.netGilPerCurrency || b.score - a.score)[0];
    const maximumReturn = returnLeader.item.netGilPerCurrency;
    const liquidityLeader = [...ranked]
      .filter((candidate) =>
        candidate !== best
        && candidate !== returnLeader
        && candidate.saleVelocity !== null
        && candidate.item.netGilPerCurrency >= maximumReturn * 0.15)
      .sort((a, b) => b.saleVelocity - a.saleVelocity || b.score - a.score)[0] || null;
    return {
      best,
      returnLeader,
      liquidityLeader,
      unverified: !ranked.some((candidate) => candidate.saleVelocity !== null),
    };
  }

  function buildIndex(conversions) {
    const groups = new Map();
    (conversions || []).forEach((item) => {
      const group = groups.get(item.currencyItemId) || [];
      group.push(item);
      groups.set(item.currencyItemId, group);
    });
    const currencies = new Map();
    const rows = new Map();
    groups.forEach((items, currencyId) => {
      const advice = analyzeCurrency(items);
      if (!advice) return;
      currencies.set(currencyId, advice);
      advice.ranked.forEach((candidate) => rows.set(conversionKey(candidate.item), candidate));
    });
    return { currencies, rows };
  }

  function purchasePlan(item, budget) {
    const available = Math.max(0, Math.floor(finite(budget) || 0));
    const cost = finite(item.currencyQuantity);
    const rewardQuantity = Math.max(1, finite(item.rewardQuantity) || 1);
    const exchanges = cost > 0 ? Math.floor(available / cost) : 0;
    const units = exchanges * rewardQuantity;
    const spent = exchanges * cost;
    const netGil = exchanges * (finite(item.netGilPerExchange) || 0);
    const velocity = finite(item.dailySaleVelocity);
    const pilotUnits = units === 0
      ? 0
      : velocity === null
        ? Math.min(units, rewardQuantity)
        : Math.min(units, Math.max(rewardQuantity, Math.ceil(velocity * 0.2)));
    return { exchanges, units, spent, netGil, pilotUnits, remaining: available - spent };
  }

  function safeExchangeCap(item) {
    const rewardQuantity = Math.max(1, finite(item.rewardQuantity) || 1);
    const velocity = finite(item.dailySaleVelocity);
    if (velocity === null || velocity <= 0) return 1;
    let units = Math.max(rewardQuantity, Math.ceil(velocity * 0.25));
    const pressure = String(item.listingDepth?.pressure || "").toUpperCase();
    if (pressure === "HIGH") units = Math.max(rewardQuantity, Math.floor(units * 0.5));
    else if (pressure === "MEDIUM") units = Math.max(rewardQuantity, Math.floor(units * 0.75));
    return Math.max(1, Math.ceil(units / rewardQuantity));
  }

  function buildPortfolio(advice, budget, predicate = () => true) {
    if (!advice) return null;
    const available = Math.max(0, Math.floor(finite(budget) || 0));
    const eligibleRanked = advice.ranked.filter((candidate) => (
      predicate(candidate.item)
      && candidate.item.currencyQuantity <= available
    ));
    if (!eligibleRanked.length) return null;
    const bestScore = eligibleRanked[0].score;
    const maximumReturn = Math.max(...eligibleRanked.map((candidate) => candidate.item.netGilPerCurrency));
    const pool = eligibleRanked
      .filter((candidate) => (
        candidate.score >= Math.max(30, bestScore * 0.55)
        && candidate.item.netGilPerCurrency >= maximumReturn * 0.15
      ))
      .slice(0, 4);
    if (!pool.length) pool.push(eligibleRanked[0]);

    const allocations = new Map(pool.map((candidate) => [candidate, 0]));
    const caps = new Map(pool.map((candidate) => [candidate, safeExchangeCap(candidate.item)]));
    let remaining = available;
    let progressed = true;
    while (progressed) {
      progressed = false;
      for (const candidate of pool) {
        const cost = finite(candidate.item.currencyQuantity) || 0;
        if (cost <= 0 || cost > remaining || allocations.get(candidate) >= caps.get(candidate)) continue;
        allocations.set(candidate, allocations.get(candidate) + 1);
        remaining -= cost;
        progressed = true;
      }
    }

    const lines = pool
      .filter((candidate) => allocations.get(candidate) > 0)
      .map((candidate) => {
        const item = candidate.item;
        const exchanges = allocations.get(candidate);
        const units = exchanges * Math.max(1, finite(item.rewardQuantity) || 1);
        return {
          candidate,
          item,
          exchanges,
          units,
          spent: exchanges * item.currencyQuantity,
          expectedNetGil: exchanges * item.netGilPerExchange,
          safeExchangeCap: caps.get(candidate),
        };
      });
    if (!lines.length) return null;
    const spent = lines.reduce((total, line) => total + line.spent, 0);
    return {
      budget: available,
      spent,
      remaining: available - spent,
      expectedNetGil: lines.reduce((total, line) => total + line.expectedNetGil, 0),
      units: lines.reduce((total, line) => total + line.units, 0),
      lines,
      hasUnverifiedVelocity: lines.some((line) => finite(line.item.dailySaleVelocity) === null),
    };
  }

  root.GilConversionAdvisor = {
    analyzeCurrency,
    buildIndex,
    conversionKey,
    buildPortfolio,
    purchasePlan,
    safeExchangeCap,
    selectForBudget,
  };
})(typeof window === "undefined" ? globalThis : window);
