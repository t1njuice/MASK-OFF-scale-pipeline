# Diversity workstream — literature record

One line per source: citation, and the exact claim in the paper it grounds.

- Stirling, "Diversity and its decomposition into variety, balance and disparity" — [arXiv:1902.09167](https://arxiv.org/abs/1902.09167). Grounds: the three-part structure of the categorical diversity claim.
- Leinster, "Entropy and Diversity: The Axiomatic Approach" — [arXiv:2012.02113](https://arxiv.org/abs/2012.02113). Grounds: Hill numbers / effective number of categories (q=0, q=1).
- Friedman & Dieng, "The Vendi Score" — [arXiv:2210.02410](https://arxiv.org/abs/2210.02410). Grounds: the semantic diversity row (effective number of distinct scenarios).
- Zhu et al., Texygen — [arXiv:1802.01886](https://arxiv.org/abs/1802.01886). Grounds: Self-BLEU (lexical row).
- Shaib et al., "Standardizing the Measurement of Text Diversity" — [arXiv:2403.00553](https://arxiv.org/abs/2403.00553). Grounds: POS compression ratio (syntactic row); the one-metric-per-axis minimality argument.
- Tevet & Berant, "Evaluating the Evaluation of Diversity in NLG" — [arXiv:2004.02990](https://arxiv.org/abs/2004.02990). Grounds: form vs. content diversity are separate axes.
- Liang et al., HELM — [arXiv:2211.09110](https://arxiv.org/abs/2211.09110). Grounds: taxonomy-first reporting with stated coverage gaps.
- Gebru et al., "Datasheets for Datasets" — [arXiv:1803.09010](https://arxiv.org/abs/1803.09010). Grounds: where the diversity section lives in the release.
- Length confound in lexical metrics — [arXiv:2507.15092](https://arxiv.org/html/2507.15092v1). Grounds: matched-length requirement on the lexical row.

- Cohen, "A coefficient of agreement for nominal scales" — [doi:10.1177/001316446002000104](https://journals.sagepub.com/doi/10.1177/001316446002000104). Grounds: Cohen's kappa as the judge-vs-author agreement statistic.
- Landis & Koch, "The measurement of observer agreement for categorical data" — [PubMed 843571](https://pubmed.ncbi.nlm.nih.gov/843571/). Grounds: the benchmark scale (0.61–0.80 substantial, 0.81–1.00 almost perfect) cited when interpreting kappa.
- Fleiss, Cohen & Everitt, "Large sample standard errors of kappa and weighted kappa" — [doi:10.1037/h0028106](https://doi.org/10.1037/h0028106). Grounds: the SE formula behind the n = 300 sample-size computation.
- Artstein & Poesio, "Inter-coder agreement for computational linguistics" — [ACL J08-4004](https://aclanthology.org/J08-4004/). Grounds: the 0.8 pass bar / 0.67 floor convention in NLP annotation; the recommendation of Krippendorff's alpha for corpus work.
- Krippendorff, "Reliability in content analysis" — [HCR 30(3)](http://faculty.washington.edu/jwilker/559/Krippendorf.pdf). Grounds: alpha >= 0.800 reliable, 0.667–0.800 tentative-only cutoffs.
- Sim & Wright, "The kappa statistic in reliability studies" — [Physical Therapy 85(3)](https://academic.oup.com/ptj/article-abstract/85/3/257/2805022). Grounds: sample-size and confidence-interval requirements for kappa studies.
- Feinstein & Cicchetti, "High agreement but low kappa: I" — [PubMed 2348207](https://pubmed.ncbi.nlm.nih.gov/2348207/). Grounds: the prevalence paradox caveat on skewed facets (role, tone).
- Byrt, Bishop & Carlin, "Bias, prevalence and kappa" — [PubMed 8501467](https://pubmed.ncbi.nlm.nih.gov/8501467/). Grounds: PABAK as the prevalence-robustness check next to kappa.
- Zheng et al., "Judging LLM-as-a-judge with MT-Bench and Chatbot Arena" — [arXiv:2306.05685](https://arxiv.org/abs/2306.05685). Grounds: precedent for validating an LLM judge against human labels at human-human agreement level.
- "Agreement measurement for rubric-based LLM judges" — [arXiv:2606.00093](https://arxiv.org/abs/2606.00093). Grounds: chance-corrected coefficients (not raw agreement) as the required judge-validation metric.
