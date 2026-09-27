# Product hypothesis: communities that emerge from shared humor

People already train recommendation systems through engagement. The proposed experience makes collective taste visible: discover other people and connected subjects through jokes that people enjoy together. It can be applied beyond humor, but humor is a useful first setting because topic, style and context can create surprisingly different communities.

## What is established, and what we are testing

Inferred overlapping communities are an established technique. [X's SimClusters overview](https://help.x.com/en/resources/recommender-systems/communities-recommendations) describes latent communities and content representations updated from engagement. [SLPA research](https://arxiv.org/abs/1202.2465) describes overlapping community detection. These sources support technical feasibility; they do not establish the originality of the proposed user experience.

The product hypothesis is that an understandable, evolving community map helps people find belonging and discover humor better than either a personal recommendation feed or a manually managed topic group. The demo tests that experience, not a novel machine-learning algorithm.

## Product choices

- Treat a share as evidence, not public consent. [Implicit-feedback research](https://yifanhu.net/PUB/cf.pdf) explains why observed behavior is noisy and why absence of activity is not a negative rating. Sending a joke does not prove liking it, and a sender cannot assign recipients an interest.
- Explain every community. Show multiple engaged people, multiple content items, recent activity, and the formation threshold.
- Allow overlap. A person can enjoy both office humor and programming humor; a bridge can be more interesting than either subject alone.
- Keep inference private until the person chooses visibility. The demo uses synthetic identities throughout. Explicit joining and leaving remain distinct from inferred interest.
- Avoid duplicate-topic fragmentation with a canonical subject vocabulary. The current experiment groups around seeded subjects. Automatic topic discovery, merge and split are future experiments.
- Separate formation from moderation. Communities can form automatically while content and behavior still follow platform rules.

## What a later pilot should measure

Measure whether community discovery leads to repeated, voluntary participation, broader topic exploration, shared conversations, and successful member-controlled exits. Track dismissals and unwanted inferences alongside clicks. Compare against a regular topic page; a beautiful graph alone does not validate belonging.

Possible later features include a community feed, conversations, shared collections, subtopics that emerge from sufficient independent activity, and explainable merge/split proposals. These should follow evidence that the first community experience is useful.
