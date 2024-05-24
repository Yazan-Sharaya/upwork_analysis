"""
This module implements functions to analyze and visualize the data collected using the `scrape_data` module.

The `perform_analysis` function performs the full suite of analysis at one go. If you want finer control over
data processing, analysis and plotting, you can call the functions separately and modify their default arguments.
The plots aren't shown by default when calling the functions separately, you need to call the `plt.show`.

The plot_* functions return the figure if you wish to perform any additional customization to it.

To save the plots after creating them, call `save_all_figures` and pass it a directory.

When the script is called directly from the command a line, a new matplotlib style is set. Otherwise, no custom style is
applied.
"""
from datetime import timedelta
import argparse
import time
import os

from sklearn.preprocessing import MultiLabelBinarizer
from matplotlib import pyplot as plt
from scipy.stats import spearmanr
import seaborn as sns
import pandas as pd


def _process_plot(plot_function: callable, fig_num: int, tick_rotation: int | None = None) -> plt.Figure:
    """
    Assign a specific figure to each plot that can be retrieved again by other functions in this module and set the
    layout to tight layout to automatically adjust spacing.
    """
    fig = plt.figure(fig_num)
    if isinstance(plot_function(), sns.FacetGrid):  # xticks doesn't work with FacetGrid.
        for ax in fig.axes:
            ax.tick_params("x", labelrotation=tick_rotation)
    else:
        plt.xticks(rotation=tick_rotation)
    fig.tight_layout()
    return fig


def read_dataset(path: str) -> pd.DataFrame:
    """Read the data in `path` into a dataframe, assign appropriate dtypes to the columns and drop duplicates."""
    df = pd.read_json(path).convert_dtypes()
    category_columns = ["proposals", "client_location", "type", "experience_level", "time_estimate"]
    integer_columns = ['budget', 'client_jobs_posted', 'client_total_spent']
    float_columns = ['client_hire_rate', 'client_hourly_rate']
    df[category_columns] = df[category_columns].astype('category')
    df[integer_columns] = df[integer_columns].apply(lambda series: pd.to_numeric(series, downcast='unsigned'))
    df[float_columns] = df[float_columns].apply(lambda series: pd.to_numeric(series, downcast='float'))
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df[~df.drop(['skills', 'time'], axis=1).duplicated()].reset_index(drop=True)
    return df


def filter_df(df: pd.DataFrame) -> pd.DataFrame:
    """Drop any rows containing NA in "budget" or "proposals" columns and caps the maximum budget to 99 percentile."""
    filtered_df = df.dropna(subset=['budget', 'proposals'], ignore_index=True).copy()
    budget_cap = int(filtered_df['budget'].quantile(0.99))
    filtered_df['budget'] = filtered_df['budget'].clip(upper=budget_cap)
    return filtered_df


def print_general_info(df: pd.DataFrame) -> None:
    """Prints general information about the dataframe and some of its columns."""
    print(df['type'].value_counts(), '\n')
    print(df['experience_level'].value_counts(), '\n')
    print(df['client_hourly_rate'].describe(), '\n')
    print(df['time_estimate'].value_counts(), '\n')
    print(df.loc[df['type'] == 'Fixed']['budget'].describe(), '\n')
    print(df.loc[df['type'] == 'Hourly']['budget'].describe())


def plot_budget_ranges(df: pd.DataFrame) -> plt.Figure:
    """Cuts the dataframe "budget" column into 16 ranges/groups and plots their frequency."""
    budget_groups = [
        '<10$', '10-20$', '20-30$', '30-40$', '40-50$', '50-100$', '100-200$', '200-300$', '300-400$', '400-500$',
        '500-1000$', '1000-5000$', '5000-10000$', "10000-50000$", ">50000$"]
    budget_bins = [0, 10, 20, 30, 40, 50, 100, 200, 300, 400, 500, 1000, 5000, 10000, 50_000, int(1e9)]
    budget_ranges = pd.cut(df['budget'], bins=budget_bins, labels=budget_groups)
    return _process_plot(
        lambda: sns.countplot(x=budget_ranges, order=budget_groups).set(
            title="Budget ranges count", xlabel="Budget Range", ylabel="Count",
            yticks=range(0, budget_ranges.value_counts().max(), 20)),
        1, 45)


def plot_job_post_frequency(df: pd.DataFrame) -> plt.Figure:
    """Plots the frequency of new job posts on each day of the week"""
    df_one_week = df[df['time'] >= (df['time'].max() - timedelta(days=7))].copy()
    df_one_week['day'] = df_one_week['time'].dt.day_name()
    return _process_plot(lambda: sns.countplot(
        df_one_week, x='day', order=['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']), 2)


def plot_highest_paying_countries(df: pd.DataFrame, n: int = 15) -> plt.Figure:
    """Plots the `n` highest paying countries."""
    counts = df.dropna(subset=['budget'])['client_location'].value_counts()
    no_four_trick_ponies = df[df['client_location'].isin(counts.index[counts > 4])]
    top_countries = (
        no_four_trick_ponies
        .groupby("client_location", observed=False)
        .budget
        .mean()
        .reset_index()
        .sort_values('budget', ascending=False)
        .head(n)
    )
    top_countries['client_location'] = top_countries['client_location'].astype('string')
    # Convert category dtype to string because seaborn will display all the categories even if they are not
    # present in chosen dataframe, this is probably a bug with seaborn.
    return _process_plot(lambda: sns.barplot(top_countries, x='client_location', y='budget'), 3, 90)


def get_most_common_skills(df: pd.DataFrame, n: int | None = None) -> dict[str, int]:
    """Return a dict containing the `n` most common skills ordered from most to least frequent and their count."""
    skills_counter = {}
    for skills_set in df['skills']:
        for skill in skills_set:
            skills_counter[skill] = skills_counter.get(skill, 0) + 1
    if not n:
        n = len(skills_counter) + 1  # To get all the values.
    return dict(sorted(skills_counter.items(), key=lambda x: x[1], reverse=True)[:n])


def plot_most_common_skills(df: pd.DataFrame, n: int | None = 20) -> plt.Figure:
    """Plots the most common skills and how many times they occurred."""
    return _process_plot(lambda: sns.barplot(
        get_most_common_skills(df, n), orient='h').set(title="Skills count", xlabel="Skill", ylabel="Count"), 4)


def transform_to_binary_skills(df: pd.DataFrame) -> pd.DataFrame:
    """Find all the unique skills in df and add each skill's presence as its own column in a copy of the original df."""
    if df[['budget', 'proposals']].isna().any().any():  # If unfiltered df is passed filter it.
        df = filter_df(df)
    mlb = MultiLabelBinarizer()
    skills_transformed = mlb.fit_transform(df['skills'])
    skills_df = pd.DataFrame(skills_transformed, columns=mlb.classes_)
    df_skills_binary = pd.concat([df, skills_df], axis=1)
    return df_skills_binary


def get_skills_correlated_with_budget(skills_df: pd.DataFrame, corr_value: float = 0.05) -> list[str]:
    """
    Calculates the Spearman correlation coefficient between each skill in the dataframe and budget.
    The chosen skills are the ones that resulted in a p value <= 0.05 and correlation coefficient >= `corr_value`.

    .. note::
        The `skills_df` should be the transformed dataframe that contains each skill as a column. This can be obtained
        using the `transform_to_binary_skills` function.
    """
    high_budget_corr_skills = []
    for column_name in skills_df.columns:
        skill_column = skills_df[column_name]
        if skill_column.dtype != object and skill_column.unique().tolist() == [0, 1]:  # Only skill columns satisfy this
            corr, p_value = spearmanr(skill_column, skills_df['budget'])
            if p_value <= 0.05 and corr >= corr_value:
                high_budget_corr_skills.append(column_name)
    return high_budget_corr_skills


def get_skills_of_interest(
        influence_budget_skills: list | None = None,
        common_skills: list | None = None,
        skills_df: pd.DataFrame | None = None
) -> list[str]:
    """
    skills of interest are defined as the intersection between skills that occur more than 15 times (common skills) and
    skills that influence the budget positively (their presence correlate with increased budget) more than 5% unless
    `influence_budget_skills` and `common_skills` arguments are passed.
    `skills_df` only needs to be passed if either `influence_budget_skills` or `common_skill` are None.
    """
    if not influence_budget_skills:
        influence_budget_skills = get_skills_correlated_with_budget(skills_df)
    if not common_skills:
        common_skills = [skill for skill, count in get_most_common_skills(skills_df).items() if count >= 15]
    return list(set(common_skills).intersection(influence_budget_skills))


def interest_df(skills_df: pd.DataFrame, skills_of_interest: list | None = None) -> pd.DataFrame:
    """Create a dataframe that only contains skill, budget and proposals columns and each row contains one skill."""
    if not skills_of_interest:
        skills_of_interest = get_skills_of_interest(skills_df=skills_df)
    df_melted = skills_df.melt(
        id_vars=['budget', 'proposals'], value_vars=skills_of_interest, var_name='skill', value_name='presence')
    # Filter only the rows where the skill is present
    df_melted = df_melted[df_melted['presence'] == 1].drop('presence', axis=1)
    return df_melted


def plot_skills_and_budget(
        skills_df: pd.DataFrame, skills_of_interest: list | None = None) -> tuple[plt.Figure, plt.Figure]:
    """Plots the chosen skills (`skills_of_interest`) and the budget associated with the skills."""
    df_melted = interest_df(skills_df, skills_of_interest)

    f1 = _process_plot(lambda: sns.boxplot(df_melted, x='skill', y='budget', order=skills_of_interest).set(
        title="Distribution of Budgets by Skill Presence"), 5, 90)

    g = sns.FacetGrid(
        df_melted, col="proposals", hue='proposals', col_wrap=2, height=8, sharex=False, sharey=False,
        col_order=['Less than 5', '5 to 10', '10 to 15', '15 to 20', '20 to 50', '50+'])
    f2 = _process_plot(lambda: g.map(sns.boxplot, "skill", "budget", order=skills_of_interest), 6, 90)
    f2.suptitle('Distribution of Budgets by Skill Presence and Number of Proposals')
    return f1, f2


def plot_skills_and_proposals(skills_df: pd.DataFrame, skills_of_interest: list | None = None) -> plt.Figure:
    """Plot a heatmap of the skills and number of proposals to show if there is a relation between them."""
    df_melted = interest_df(skills_df, skills_of_interest)
    contingency_table = pd.crosstab(df_melted['proposals'], df_melted['skill'], normalize='columns').reindex(
        ['Less than 5', '5 to 10', '10 to 15', '15 to 20', '20 to 50', '50+']).T
    return _process_plot(lambda: sns.heatmap(contingency_table, annot=True, fmt='.2g'), 7)


def save_all_figures(directory: str, randomize_name: bool = True) -> None:
    """Save *only* all the figures created by this module in `directory`."""
    fig_num_mapping = {
        1: "budget_ranges", 2: "post_frequency", 3: "highest_paying_countries", 4: "common_skills",
        5: "skills_budget", 6: "skills_budget_grid", 7: "skills_proposals"}
    if not os.path.isdir(directory):
        os.mkdir(directory)
    print(f"Saving to {directory}")
    for fig_num in plt.get_fignums():
        if fig_num in range(1, 8):
            fig_name = fig_num_mapping[fig_num] + "_plot"
            if randomize_name:
                fig_name += f"_{int(time.time())}"
            plt.figure(fig_num).savefig(os.path.join(directory, f"{fig_name}.png"))


def perform_analysis(dataset_path: str, save_plots_dir: str | None = None, show_plots: bool = True) -> None:
    """
    Perform all the data analysis techniques available in this module and plot the result.

    Parameters
    ----------
    dataset_path: str
        The path to the json file containing the scraped data.
    save_plots_dir: str, optional
        Where to save the plots after creating them. If None or an empty string, the plots won't be saved.
    show_plots: bool, optional
        Whether to show the plots after creating them. Default is True
    """
    df = read_dataset(dataset_path)
    print_general_info(df)
    plot_budget_ranges(df)
    plot_highest_paying_countries(df)
    plot_job_post_frequency(df)
    plot_most_common_skills(df)
    skills_df = transform_to_binary_skills(df)
    plot_skills_and_budget(skills_df)
    plot_skills_and_proposals(skills_df)
    if save_plots_dir:
        save_all_figures(save_plots_dir)
    if show_plots:
        plt.show()


if __name__ == '__main__':
    sns.set(style='whitegrid', palette="deep", font_scale=1.1, rc={"figure.figsize": [10, 6]})
    parser = argparse.ArgumentParser(
        description="Perform data analysis on the data collected by scraping upwork and plot the data.")
    parser.add_argument(
        "dataset_path", type=str, help="The path to the scraped data.")
    parser.add_argument(
        "-o", "--save-dir", type=str, help="The directory to save the plots to. If not passed, don't save the plots.")
    parser.add_argument(
        "-s", "--show", action="store_true", help="Whether to show the plots. Off by default.")
    args = parser.parse_args()
    scraped_data_path = args.dataset_path
    save_directory = args.save_dir
    show = args.show
    perform_analysis(scraped_data_path, save_directory, show)
